import json
import os
import time
import urllib.error
import urllib.request

import appdaemon.plugins.hass.hassapi as hass

# Giorni: weekday() 0=lun ... 6=dom -> chiavi del calendario
GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]

# Evento emesso dall'integrazione a ogni modifica delle options:
# refresh immediato della config senza attendere il refresh periodico.
EVENT_CONFIG_UPDATED = "climaoro_config_updated"

VALUE_COMFORT = "comfort"
VALUE_ECO = "eco"
VALUE_AUTONOMO = "autonomo"


class Climaoro(hass.Hass):
    """Gestione centralizzata Climaoro, completamente generica.

    Non usa NESSUN entity_id hardcoded: carica la configurazione runtime
    da `/api/climaoro/config` (esposta dal custom component) che risolve
    gli entity_id correnti dal registry HA. Se l'utente rinomina un'entita',
    basta rileggere la config (refresh periodico) e tutto continua a
    funzionare.

    La config runtime ha la forma:
        {"appartamenti": [{"id", "nome", "attivo", "soglia_pesi",
                           "entities": {attivo, soglia_pesi},
                           "gruppi": [{"id", "label",
                                       "delta_accensione_comfort",
                                       "delta_accensione_eco",
                                       "delta_spegnimento_comfort",
                                       "delta_spegnimento_eco",
                                       "calendar",
                                       "entities", "stanze"}]}],
         "entities": {...}}
    Ogni appartamento ha il proprio master (attivo) e soglia pesi; i gruppi
    (calendari/delta) sono copie indipendenti per appartamento.

    I delta si sommano a temp_salvata e definiscono il setpoint da
    applicare al climate (il termostato aggiunge la sua isteresi ± 0.5):
      - delta_accensione: usato quando il termostato e' SPENTO (attesa).
        Setpoint = temp_salvata + delta_acc; il termostato accende a
        temp_salvata + delta_acc - 0.5. Es. temp_salvata 20, delta -1:
        setpoint 19, accende a 18.5.
      - delta_spegnimento: usato quando il termostato e' ACCESO (lavoro).
        Setpoint = temp_salvata + delta_sp; il termostato spegne a
        temp_salvata + delta_sp + 0.5. Es. temp_salvata 20, delta 0:
        setpoint 20, spegne a 20.5.
    Una stanza in attesa diventa RICHIEDENTE (candidata ad accendere)
    quando temp <= temp_salvata - 0.5 (inizio della banda isteresi
    centrata su temp_salvata: li' il termostato partirebbe da solo).
    Se i pesi raggiungono la soglia (o c'e' priorita'/emergenza) viene
    accesa SCRIVENDO il setpoint di spegnimento (temp_salvata + delta_sp):
    e' quella scrittura a far cambiare stato al termostato. Se i pesi NON
    raggiungono la soglia, l'emergenza individuale parte da
    temp <= temp_salvata + delta_acc - 0.4 (0.1 sopra il punto in cui il
    termostato accenderebbe da solo), scrivendo il setpoint di spegnimento.

    Args attesi in apps.yaml:
        ha_url:   base URL di HA (es. http://supervisor/core nell'addon)
        token:    token long-lived di HA (o ha_token per compatibilita')
        refresh_sec:  quanto spesso rileggere la config (default 600)
        cycle_sec:    quanto spesso girare il ciclo di controllo (default 60)
        rinnovo_sec:  quanto spesso premere i pulsanti "rinnovo" (default 240)
    """

    def initialize(self):
        self.ha_url = self.args.get("ha_url", "http://supervisor/core").rstrip("/")
        self.ha_token = (
            os.environ.get("SUPERVISOR_TOKEN")
            or self.args.get("token")
            or self.args.get("ha_token", "")
        )
        self.refresh_sec = self.args.get("refresh_sec", 600)
        self.cycle_sec = self.args.get("cycle_sec", 60)
        self.rinnovo_sec = self.args.get("rinnovo_sec", 240)
        self.check_centralizzata_sec = self.args.get("check_centralizzata_sec", 1200)

        self.config = None
        self.config_time = 0

        self._load_config()
        if self.config is None:
            self.log("Config non ancora disponibile: ritento tra 30s.", level="WARNING")
            self.run_in(self._retry_load, 30)
            return

        self._schedule()

    def _retry_load(self, kwargs):
        self._load_config()
        if self.config is None:
            self.run_in(self._retry_load, 30)
            return
        self._schedule()

    def _schedule(self):
        """Pianifica tutte le attivita' periodiche + ascolto dei master."""
        self.run_every(self._refresh_config, "now", self.refresh_sec)
        self.run_every(self.control_cycle, "now", self.cycle_sec)
        self.run_every(self.rinnovo_modalita, "now", self.rinnovo_sec)
        self.listen_event(self._on_config_updated, EVENT_CONFIG_UPDATED)
        for ap in self._apartamenti():
            attivo_eid = (ap.get("entities") or {}).get("attivo")
            if attivo_eid:
                self.listen_state(
                    self._on_attivo_changed, attivo_eid, apartment_id=ap.get("id")
                )
        self.run_every(self.controllo_centralizzata, "now", self.check_centralizzata_sec)
        self.log("App Climaoro avviata (appartamenti: %d)", len(self._apartamenti()))

    def _apartamenti(self):
        """Lista appartamenti dalla config (fallback: singolo globale legacy)."""
        apps = (self.config or {}).get("appartamenti")
        if apps is not None:
            return apps
        if self.config and "global" in self.config:
            g = self.config.get("global") or {}
            return [
                {
                    "id": "casa",
                    "nome": "Casa",
                    "attivo": g.get("attivo"),
                    "soglia_pesi": g.get("soglia_pesi"),
                    "entities": g.get("entities") or {},
                    "gruppi": self.config.get("gruppi", []),
                }
            ]
        return []

    def _ap_by_id(self, ap_id):
        for ap in self._apartamenti():
            if ap.get("id") == ap_id:
                return ap
        return None

    # ---------------------------------------------------------------- config
    def _load_config(self):
        try:
            self.config = self._fetch_config()
            self.config_time = time.time()
            self.log("Config runtime caricata (%d appartamenti, %d entita').",
                     len(self.config.get("appartamenti", [])),
                     len(self.config.get("entities", {})))
        except Exception as err:
            self.config = None
            self.log("Errore caricamento config: %s", err, level="ERROR")

    def _refresh_config(self, kwargs):
        try:
            new = self._fetch_config()
            self.config = new
            self.config_time = time.time()
        except Exception as err:
            self.log("Errore refresh config: %s (uso config precedente)", err, level="WARNING")

    def _on_config_updated(self, event_name, data, kwargs):
        """La config e' cambiata in HA: rileggi subito la runtime config."""
        self.log("Evento %s ricevuto: refresh immediato della config.", event_name)
        self._refresh_config(None)

    def _fetch_config(self):
        url = f"{self.ha_url}/api/climaoro/config"
        token = (
            os.environ.get("SUPERVISOR_TOKEN") or self.ha_token or ""
        )
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    # ------------------------------------------------------------- utilities
    def _float_safe(self, value, default=None):
        if value in [None, "unavailable", "unknown", ""]:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def _fascia_corrente(self, gruppo):
        """Fascia (comfort/eco/autonomo) del gruppo all'ora corrente."""
        cal = gruppo.get("calendar") or {}
        giorni = cal.get(GIORNI[self.datetime().weekday()])
        if not giorni:
            return VALUE_ECO
        ora = self.datetime().hour
        if 0 <= ora < len(giorni):
            return giorni[ora]
        return VALUE_ECO

    def _delta_gruppo(self, gruppo, campo):
        """Delta (accensione/spegnimento) del gruppo nella fascia corrente."""
        fascia = self._fascia_corrente(gruppo)
        if fascia == VALUE_COMFORT:
            return self._float_safe(gruppo.get(f"delta_{campo}_comfort"))
        if fascia == VALUE_ECO:
            return self._float_safe(gruppo.get(f"delta_{campo}_eco"))
        return None  # autonomo: nessun delta

    # -------------------------------------------------------------- azioni
    def rinnovo_modalita(self, kwargs):
        if self.config is None:
            return
        for ap in self._apartamenti():
            self._rinnovo_apartment(ap)

    def _rinnovo_apartment(self, ap):
        attivo_eid = (ap.get("entities") or {}).get("attivo")
        if attivo_eid and self.get_state(attivo_eid) == "off":
            self.log("Rinnovo saltato: master '%s' spento (entita').", ap.get("id", "?"))
            return

        for gruppo in ap.get("gruppi", []):
            if self._fascia_corrente(gruppo) == VALUE_AUTONOMO:
                continue
            for stanza in gruppo.get("stanze", []):
                eid_incl = (stanza.get("entities") or {}).get("inclusione")
                if eid_incl and self.get_state(eid_incl) != "on":
                    continue
                eid_rinnovo = (stanza.get("entities") or {}).get("rinnovo")
                if eid_rinnovo:
                    self.call_service("button/press", entity_id=eid_rinnovo)
                    self.log("Rinnovo modalita' stanza '%s' (%s)", stanza.get("nome"), eid_rinnovo)

    def _on_attivo_changed(self, entity, attribute, old, new, kwargs):
        """All'attivazione del master accende la modalita' centralizzata."""
        if self.config is None:
            return
        if new == "on":
            ap_id = kwargs.get("apartment_id") or "casa"
            self.log("Master '%s' acceso: attivazione modalita' centralizzata.", ap_id)
            self._refresh_config(None)
            ap = self._ap_by_id(ap_id)
            if ap:
                self._attiva_centralizzata(ap)

    def controllo_centralizzata(self, kwargs):
        """Controllo periodico: con master acceso, ri-assert della centralizzata."""
        if self.config is None:
            return
        self._refresh_config(None)
        for ap in self._apartamenti():
            attivo_eid = (ap.get("entities") or {}).get("attivo")
            stato = self.get_state(attivo_eid) if attivo_eid else None
            if stato == "on":
                self._attiva_centralizzata(ap)

    def _attiva_centralizzata(self, ap):
        """Accende la modalita' centralizzata per le stanze gestibili."""
        for gruppo in ap.get("gruppi", []):
            if self._fascia_corrente(gruppo) == VALUE_AUTONOMO:
                continue
            for stanza in gruppo.get("stanze", []):
                e = stanza.get("entities") or {}
                eid_incl = e.get("inclusione")
                if eid_incl and self.get_state(eid_incl) != "on":
                    continue
                eid_modalita = e.get("modalita")
                if not eid_modalita or self.get_state(eid_modalita) == "on":
                    continue
                self.call_service("switch/turn_on", entity_id=eid_modalita)
                self.log("Attivata modalita' centralizzata stanza '%s' (%s).",
                         stanza.get("nome"), eid_modalita)

    def _comando_sicuro_per_stanza(self, stanza, entity, service, data, stanza_id):
        """Attiva la modalita' centralizzata se serve, poi esegue il comando.

        Prima di ogni comando la centralizzata deve essere attiva: se non lo
        e', viene attivata e si ricontrolla; se a quel punto e' attiva si
        invia il comando, altrimenti si riprova un'altra volta.
        """
        eid_modalita = (stanza.get("entities") or {}).get("modalita")
        if not eid_modalita:
            data["entity_id"] = entity
            self.call_service(service, **data)
            return True

        for _ in range(2):
            if self.get_state(eid_modalita) != "on":
                self.log("Stanza %s: modalita' centralizzata spenta, attivazione.", stanza_id)
                self.call_service("switch/turn_on", entity_id=eid_modalita)
                time.sleep(2)
            if self.get_state(eid_modalita) == "on":
                data["entity_id"] = entity
                self.call_service(service, **data)
                return True

        self.log("ERRORE: Stanza %s - modalita' centralizzata non attivabile.", stanza_id, level="ERROR")
        return False

    # ------------------------------------------------------------ controllo
    def control_cycle(self, kwargs):
        self.log("----- CICLO INIZIATO -----")
        if self.config is None:
            self.log("Config non disponibile, ciclo saltato.")
            return

        for ap in self._apartamenti():
            self._cycle_apartment(ap)

        self.log("----- CICLO TERMINATO -----")

    def _cycle_apartment(self, ap):
        ap_id = ap.get("id", "?")
        attivo_eid = (ap.get("entities") or {}).get("attivo")
        if attivo_eid and self.get_state(attivo_eid) == "off":
            self.log("Master '%s' spento, nessuna azione.", ap_id)
            return

        soglia_eid = (ap.get("entities") or {}).get("soglia_pesi")
        soglia_pesi = self._float_safe(self.get_state(soglia_eid)) if soglia_eid else None
        if soglia_pesi is None:
            self.log("ERRORE: soglia_pesi non disponibile per '%s' - ciclo annullato.", ap_id, level="ERROR")
            return

        self.log("Appartamento '%s': %s %02d:%02d", ap_id,
                 GIORNI[self.datetime().weekday()],
                 self.datetime().hour, self.datetime().minute)

        for gruppo in ap.get("gruppi", []):
            self._controlla_gruppo(gruppo, soglia_pesi)

    def _controlla_gruppo(self, gruppo, soglia_pesi):
        fascia = self._fascia_corrente(gruppo)
        self.log("Gruppo '%s': fascia=%s", gruppo.get("label", gruppo.get("id")), fascia)
        if fascia == VALUE_AUTONOMO:
            self.log("Gruppo '%s': fascia autonomo - termostati al firmware, salto.", gruppo.get("id"))
            return

        delta_acc = self._delta_gruppo(gruppo, "accensione")
        delta_sp = self._delta_gruppo(gruppo, "spegnimento")
        if delta_acc is None or delta_sp is None:
            self.log("ERRORE: Gruppo '%s': delta non disponibili.", gruppo.get("id"), level="ERROR")
            return

        zone_ok = []
        for stanza in gruppo.get("stanze", []):
            e = stanza.get("entities") or {}
            eid_incl = e.get("inclusione")
            if eid_incl and self.get_state(eid_incl) != "on":
                self.log("Stanza %s: esclusa (inclusione off).", stanza.get("nome"))
                continue

            eid_clima = e.get("clima")
            hvac_mode = self.get_state(eid_clima) if eid_clima else None
            if hvac_mode != "heat":
                self.log("Stanza %s: modalita' '%s' - non inclusa.", stanza.get("nome"), hvac_mode)
                continue

            raw_t_salvata = self.get_state(e.get("temp_salvata"))
            t_salvata = self._float_safe(raw_t_salvata)
            if t_salvata is None:
                self.log("ERRORE: Stanza %s: temp_salvata non disponibile.", stanza.get("nome"), level="ERROR")
                continue

            temp = self.get_state(eid_clima, attribute="current_temperature")
            if temp in [None, "unavailable", "unknown"]:
                self.log("ERRORE: Stanza %s: temperatura corrente non disponibile.", stanza.get("nome"), level="ERROR")
                continue

            setpoint = self._float_safe(self.get_state(eid_clima, attribute="temperature"))
            hvac_action = self.get_state(eid_clima, attribute="hvac_action")
            if setpoint is None:
                self.log("ERRORE: Stanza %s: setpoint non valido.", stanza.get("nome"), level="ERROR")
                continue

            zone_ok.append({
                "stanza": stanza, "nome": stanza.get("nome"),
                "t_salvata": t_salvata, "temp": float(temp),
                "setpoint": setpoint, "action": hvac_action,
            })
            self.log("Stanza %s: OK (temp_salvata=%.1f, temp=%.1f, setpoint=%.1f, action=%s)",
                     stanza.get("nome"), t_salvata, float(temp), setpoint, hvac_action)

        if not zone_ok:
            self.log("Nessuna stanza gestibile nel gruppo '%s'.", gruppo.get("id"))
            return

        lista_richieste = []
        zone_riscaldamento = []
        totale_pesi = 0.0

        for z in zone_ok:
            setpoint_on = z["t_salvata"] + delta_acc
            setpoint_off = z["t_salvata"] + delta_sp
            soglia_richiesta = z["t_salvata"] - 0.5

            self.log("Stanza %s: attesa accende a %.1f (setpoint %.1f), lavoro spegne a %.1f (setpoint %.1f), richiesta a %.1f, reale=%.1f, action=%s",
                     z["nome"], setpoint_on - 0.5, setpoint_on, setpoint_off + 0.5, setpoint_off,
                     soglia_richiesta, z["temp"], z["action"])

            if z["action"] == "heating":
                zone_riscaldamento.append(z["nome"])
                self.log("Stanza %s sta scaldando - priorita'.", z["nome"])
                continue

            if not self._comando_sicuro_per_stanza(
                z["stanza"], z["stanza"]["entities"].get("clima"),
                "climate/set_temperature", {"temperature": setpoint_on}, z["nome"]
            ):
                continue
            self.log("Stanza %s: setpoint allineato all'accensione (%.1f C).", z["nome"], setpoint_on)

            if z["temp"] <= soglia_richiesta:
                lista_richieste.append(z["nome"])
                eid_peso = (z["stanza"].get("entities") or {}).get("peso")
                peso = self._float_safe(self.get_state(eid_peso), 0.0) if eid_peso else 0.0
                totale_pesi += peso
                self.log("Stanza %s aggiunta a richieste (peso=%.1f, tot=%.1f)", z["nome"], peso, totale_pesi)

        if zone_riscaldamento:
            self.log("Priorita': zone in riscaldamento -> accendo le richiedenti.")
            for nome in lista_richieste:
                self._accendi_stanza(gruppo, nome)
        elif totale_pesi >= soglia_pesi:
            self.log("Soglia pesi raggiunta (%.1f >= %.1f) -> accensioni collettive.", totale_pesi, soglia_pesi)
            for nome in lista_richieste:
                self._accendi_stanza(gruppo, nome)
        else:
            self.log("Emergenza individuale.")
            for z in zone_ok:
                if z["action"] == "heating":
                    continue
                soglia_emergenza = z["t_salvata"] + delta_acc - 0.4
                if z["temp"] <= soglia_emergenza:
                    self.log("Emergenza stanza %s: %.1f <= %.1f", z["nome"], z["temp"], soglia_emergenza)
                    self._accendi_stanza(gruppo, z["nome"])

    def _accendi_stanza(self, gruppo, nome):
        stanza = self._stanza_by_name(gruppo, nome)
        if stanza is None:
            return
        e = stanza.get("entities") or {}
        t_salvata = self._float_safe(self.get_state(e.get("temp_salvata")))
        if t_salvata is None:
            self.log("ERRORE: Stanza %s: temp_salvata mancante - accensione saltata.", nome, level="ERROR")
            return
        delta_sp = self._delta_gruppo(gruppo, "spegnimento")
        if delta_sp is None:
            return
        setpoint_off = t_salvata + delta_sp
        self._comando_sicuro_per_stanza(
            stanza, e.get("clima"), "climate/set_temperature",
            {"temperature": setpoint_off}, nome
        )

    def _stanza_by_name(self, gruppo, nome):
        for stanza in gruppo.get("stanze", []):
            if stanza.get("nome") == nome:
                return stanza
        return None
