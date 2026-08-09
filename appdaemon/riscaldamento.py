import appdaemon.plugins.hass.hassapi as hass
import time

class riscaldamento_centralizzato(hass.Hass):
    def initialize(self):
        self.num_zone = self.args.get("numero_zone", 6)
        self.run_every(self.control_cycle, "now", 60)
        self.run_every(self.rinnovo_modalita, "now", 240)

    def rinnovo_modalita(self, kwargs):
        if self.args.get("attivo") and self.get_state(self.args["attivo"]) == "off":
            return
        for i in range(1, self.num_zone + 1):
            zona = self.args.get(f"zona{i}")
            if zona and self.get_state(zona["inclusione"]) == "on":
                rinnovo = zona.get("rinnovo_modalita")
                if rinnovo:
                    self.call_service("button/press", entity_id=rinnovo)
                    self.log(f"Rinnovo modalità centralizzata zona {i}")

    def _float_safe(self, value, default=None):
        if value in [None, "unavailable", "unknown"]:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def _attiva_modalita_centralizzata(self, switch_modalita):
        if not switch_modalita:
            return True
        if self.get_state(switch_modalita) == "on":
            return True
        self.call_service("switch/turn_on", entity_id=switch_modalita)
        time.sleep(2)
        return self.get_state(switch_modalita) == "on"

    def _comando_sicuro_per_zona(self, zona, entity, service, data, zona_id):
        switch_modalita = zona.get("modalita_centralizzata")
        if not switch_modalita:
            data["entity_id"] = entity
            self.call_service(service, **data)
            return True

        if self.get_state(switch_modalita) == "on":
            data["entity_id"] = entity
            self.call_service(service, **data)
            return True

        self.log(f"Zona {zona_id}: modalità centralizzata spenta, tentativo di accensione.")
        if not self._attiva_modalita_centralizzata(switch_modalita):
            self.log(f"ERRORE: Zona {zona_id} – modalità centralizzata non attivabile.", level="ERROR")
            return False

        data["entity_id"] = entity
        self.call_service(service, **data)
        return True

    def control_cycle(self, kwargs):
        self.log("----- CICLO INIZIATO -----")

        if self.args.get("attivo") and self.get_state(self.args["attivo"]) == "off":
            self.log("Master spento, nessuna azione.")
            return

        zone_ok = []
        for i in range(1, self.num_zone + 1):
            zona = self.args.get(f"zona{i}")
            if not zona:
                continue
            if self.get_state(zona["inclusione"]) != "on":
                self.log(f"Zona {i}: esclusa (inclusione off).")
                continue

            hvac_mode = self.get_state(zona["clima"])
            if hvac_mode != "heat":
                self.log(f"Zona {i}: modalità '{hvac_mode}' invece di 'heat' – considerata non inclusa.")
                continue

            raw_t_salvata = self.get_state(zona["temp_salvata"])
            t_salvata = self._float_safe(raw_t_salvata)
            if t_salvata is None:
                self.log(f"ERRORE: Zona {i} temperatura salvata non disponibile – esclusa.", level="ERROR")
                continue

            temp = self.get_state(zona["clima"], attribute="current_temperature")
            if temp in [None, "unavailable", "unknown"]:
                self.log(f"ERRORE: Zona {i} temperatura non disponibile – esclusa.", level="ERROR")
                continue

            temp_reale = float(temp)
            setpoint_corrente = self._float_safe(
                self.get_state(zona["clima"], attribute="temperature")
            )
            hvac_action = self.get_state(zona["clima"], attribute="hvac_action")
            if setpoint_corrente is None:
                self.log(f"ERRORE: Zona {i} setpoint non valido – esclusa.", level="ERROR")
                continue

            zone_ok.append((i, t_salvata, temp_reale, setpoint_corrente, hvac_action))
            self.log(f"Zona {i}: OK (temp_salvata={t_salvata}°C, temp={temp_reale}°C, setpoint={setpoint_corrente}°C, action={hvac_action})")

        if not zone_ok:
            self.log("Nessuna zona gestibile in questo ciclo.")
            return

        ora = self.datetime().hour
        giorno = (7 <= ora < 20)
        self.log(f"Ora: {ora}, fascia: {'giorno' if giorno else 'notte'}")

        soglia_pesi = self._float_safe(self.get_state(self.args["soglia_pesi"]))
        if soglia_pesi is None:
            self.log("ERRORE: soglia_pesi non disponibile – ciclo annullato.", level="ERROR")
            return

        totale_pesi = 0
        lista_richieste = []
        zone_con_richiesta_attiva = []

        for i, t_salvata, temp_reale, setpoint_corrente, hvac_action in zone_ok:
            zona = self.args[f"zona{i}"]

            if giorno:
                ds = self._float_safe(self.get_state(zona["delta_squadra_giorno"]))
                dsp = self._float_safe(self.get_state(zona["delta_spegnimento_giorno"]))
            else:
                ds = self._float_safe(self.get_state(zona["delta_squadra_notte"]))
                dsp = self._float_safe(self.get_state(zona["delta_spegnimento_notte"]))
            if ds is None or dsp is None:
                self.log(f"ERRORE: Zona {i} delta mancanti – esclusa.", level="ERROR")
                continue

            guardia = t_salvata - ds
            setpoint_lavoro = t_salvata + dsp

            self.log(f"Zona {i}: guardia={guardia:.1f}, lavoro={setpoint_lavoro:.1f}, "
                     f"reale={temp_reale:.1f}, setpoint={setpoint_corrente:.1f}, action={hvac_action}")

            if hvac_action == "heating":
                zone_con_richiesta_attiva.append(i)
                self.log(f"Zona {i} sta scaldando – priorità.")
                continue

            if not self._comando_sicuro_per_zona(
                zona, zona["clima"], "climate/set_temperature",
                {"temperature": guardia}, zona_id=i
            ):
                continue

            self.log(f"Zona {i}: setpoint allineato a guardia ({guardia}°C).")

            if temp_reale <= t_salvata - 0.5:
                lista_richieste.append(i)
                peso = self._float_safe(self.get_state(zona["peso"]))
                if peso is None:
                    peso = 0.0
                totale_pesi += peso
                self.log(f"Zona {i} aggiunta a richieste (peso={peso}, tot={totale_pesi})")

        # --- FASE 2: decisione ---
        if len(zone_con_richiesta_attiva) > 0:
            self.log("Priorità: zone già in riscaldamento → accendo le richiedenti.")
            for i in lista_richieste:
                self._accendi_zona(i, giorno)
        elif totale_pesi >= soglia_pesi:
            self.log("Soglia pesi raggiunta → accensioni collettive.")
            for i in lista_richieste:
                self._accendi_zona(i, giorno)
        else:
            self.log("Fase 3: emergenza individuale.")
            for i, t_salvata, temp_reale, _, hvac_action in zone_ok:
                if hvac_action == "heating":
                    continue
                zona = self.args[f"zona{i}"]
                if giorno:
                    ds = self._float_safe(self.get_state(zona["delta_squadra_giorno"]))
                    dsp = self._float_safe(self.get_state(zona["delta_spegnimento_giorno"]))
                else:
                    ds = self._float_safe(self.get_state(zona["delta_squadra_notte"]))
                    dsp = self._float_safe(self.get_state(zona["delta_spegnimento_notte"]))
                if ds is None or dsp is None:
                    continue
                guardia = t_salvata - ds
                if temp_reale <= guardia - 0.4:
                    self.log(f"Emergenza zona {i}: {temp_reale:.1f}°C ≤ {guardia - 0.4:.1f}°C")
                    self._accendi_zona(i, giorno)

        self.log("----- CICLO TERMINATO -----")

    def _accendi_zona(self, i, giorno):
        zona = self.args[f"zona{i}"]
        t_salvata = self._float_safe(self.get_state(zona["temp_salvata"]))
        if t_salvata is None:
            self.log(f"ERRORE: Zona {i} temperatura salvata mancante – accensione saltata.", level="ERROR")
            return
        if giorno:
            dsp = self._float_safe(self.get_state(zona["delta_spegnimento_giorno"]))
        else:
            dsp = self._float_safe(self.get_state(zona["delta_spegnimento_notte"]))
        if dsp is None:
            self.log(f"ERRORE: Zona {i} delta spegnimento mancante – accensione saltata.", level="ERROR")
            return
        temp = t_salvata + dsp
        self._comando_sicuro_per_zona(
            zona, zona["clima"], "climate/set_temperature",
            {"temperature": temp}, zona_id=i
        )