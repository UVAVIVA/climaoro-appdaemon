# CLIMAORO - Integrazione HA (custom component + AppDaemon)

Gestione centralizzata del riscaldamento CLIMAORO per Home Assistant.

I termostati hanno autonomia locale (firmware). Questa integrazione
permette la **gestione centralizzata**: una singola app AppDaemon legge
le impostazioni (gruppi, calendari 7x24, delta, pesi) e pilota tutti i
termostati collettivamente, disattivando di fatto la loro funzione
autonoma quando serve.

**Nessun entity_id hardcoded**: tutto (app e pannello) risolve le
entità dal registry HA tramite l'endpoint `/api/climaoro/config` che
restituisce la struttura completa con gli entity_id correnti. Se l'utente
rinomina un'entità, basta rileggere la config e tutto continua a
funzionare (rename-proof).

## Architettura

```
custom_components/climaoro/   Custom component HA
  config_flow.py              Wizard con selettori entity
  __init__.py                 Endpoint REST + websocket config runtime
  number.py / switch.py / sensor.py   Entità di contorno
appdaemon/
  climaoro.py                 App AppDaemon generica (logica centralizzata)
  apps.yaml                   Config app (solo ha_url + ha_token)
ha_config/                    Esempi legacy (architettura v1)
test/                         Esempi legacy di simulazione
PERCORSO.txt                  Sintesi del progetto (leggere per primo)
```

### Modello

- **Stanze**: nome, **appartamento** di appartenenza, gruppo di
  appartenenza, **peso** e **inclusione** (le uniche cose individuali) +
  le 4 entità chiave del termostato:
  - `climate.<dev>_climatizzazione`
  - `number.<dev>_temperatura_salvata`
  - `switch.<dev>_modalita_centralizzata`
  - `button.<dev>_rinnovo_modalita_centralizzata`
  (non c'è un limite fisso al numero di stanze, serve almeno una stanza)
- **Gruppi** fissi GIORNO / NOTTE / SERVIZI (opzionali). Ogni gruppo di
  ogni appartamento ha:
  - 4 **delta** (accensione e spegnimento, per le 2 fasce comfort/eco),
    che si **sommano** a `temp_salvata` per definire i setpoint
  - un **calendario 7x24** con tendina `eco` / `comfort` / `autonomo`
    (autonomo = i termostati del gruppo tornano al firmware)
  - per la Casa: `number.climaoro_<gruppo>_delta_*` (accensione e
    spegnimento per comfort/eco) e `sensor.climaoro_<gruppo>_calendario`
  - per il secondo appartamento: `number.climaoro_appartamento_<gruppo>_delta_*`
    e `sensor.climaoro_appartamento_<gruppo>_calendario`
- **Appartamenti**: l'integrazione gestisce 2 unità indipendenti
  (Casa + Appartamento). Ogni appartamento ha il proprio **Globale**
  (master `switch.climaoro_attivo` / `switch.climaoro_appartamento_attivo`
  + `number.climaoro_soglia_pesi` / `number.climaoro_appartamento_soglia_pesi`)
  e **proprie copie** dei gruppi (calendari/delta). La Casa conserva i
  unique_id storici (`climaoro_attivo`, `climaoro_soglia_pesi`); il secondo
  appartamento usa il prefisso `climaoro_appartamento_`. Ogni stanza
  appartiene a un appartamento.

### Logica di controllo (app AppDaemon)

Ogni ciclo (60s), per ogni gruppo in fascia non-autonoma:

1. Calcola i setpoint dalla fascia corrente:
   - **attesa** (termostato spento): `setpoint = temp_salvata + delta_accensione`
     (il termostato accende a `setpoint - 0.5`)
   - **lavoro** (termostato acceso): `setpoint = temp_salvata + delta_spegnimento`
     (il termostato spegne a `setpoint + 0.5`)
2. Allinea il setpoint all'attesa e raccoglie le stanze in **richiesta**
   (temp reale <= temp_salvata - 0.5, soglia indipendente dal delta
   accensione), sommandone i pesi.
3. Se qualche stanza è già in **riscaldamento** (`hvac_action=heating`):
   priorità a lei, si accendono le richiedenti.
4. Altrimenti, se **totale pesi >= soglia**: accensione collettiva
   (tutte le richiedenti, scritto il setpoint di lavoro).
5. Altrimenti **emergenza individuale**: stanza con temp <=
   temp_salvata + delta_accensione - 0.4 (0.1 sopra l'accensione
   autonoma del termostato) accesa a lavoro.

Nota: i `delta_*` si **sommano** a temp_salvata (possono essere
negativi o positivi). I delta di accensione definiscono quando il
termostato parte da solo; i delta di spegnimento quando si spegne
dopo un'accensione.

Sicurezza e centralizzata:
- Prima di un comando a un climate l'app verifica che lo
  `switch.<dev>_modalita_centralizzata` sia attivo; se spento lo accende
  e ricontrolla (max 2 tentativi), solo poi invia il comando.
- Quando il master `switch.climaoro_attivo` passa su **ON**, l'app
  attiva subito la modalità centralizzata di tutte le stanze incluse
  (non in fascia `autonomo`). Allo spegnimento del master **non**
  spegne nulla: basta che il rinnovo si fermi.
- Un check periodico (default **20 min**, configurabile con
  `check_centralizzata_sec`) ri-asserta la centralizzata se il master è
  ancora ON (copre anche i riavvii dell'app con master già attivo).
- Il timer di rinnovo (default 240s, `rinnovo_sec`) preme il pulsante
  "rinnovo" delle stanze incluse (non in fascia autonoma); quando il
  master è OFF il rinnovo resta fermo ("Rinnovo saltato: master spento").

## Installazione

1. Copiare `custom_components/climaoro/` in `<config>/custom_components/`
   e riavviare HA.
2. **Aggiungi integrazione -> Climaoro**: il wizard guida nell'inserimento
   delle entità chiave delle stanze; al termine crea le entità di contorno.
3. Installare l'addon **AppDaemon**; copiare `appdaemon/climaoro.py` e
   `appdaemon/apps.yaml` in `<addon_configs>/<id_appdaemon>/apps/`
   (`<id_appdaemon>` è l'id dell'addon, es. `a0d7b954_appdaemon`).
4. In `apps.yaml` impostare:
   ```yaml
   climaoro:
     module: climaoro
     class: Climaoro
     ha_url: http://<ip-ha>:80
     ha_token: <token long-lived HA>
   ```
   Se l'app gira nell'addon AppDaemon con il permesso
   `homeassistant_api`, usa automaticamente il `SUPERVISOR_TOKEN`
   (`ha_url: http://supervisor/core`) e il token non serve.
5. Riavviare AppDaemon. Il pannello "Climaoro" è disponibile a
   `/climaoro-panel`.

Configurabili in `apps.yaml` (oltre a `ha_url`/`ha_token`):
`refresh_sec` (600), `cycle_sec` (60), `rinnovo_sec` (240),
`check_centralizzata_sec` (1200).

## Pannello multi-vista

La dashboard "Climaoro" (url_path `climaoro-panel`) è organizzata in
**viste separate** (una per pagina, in ordine nel menu laterale):

- **Globale** (`globale`): master `climaoro_attivo` + soglia pesi.
- Una vista per gruppo (`giorno`, `notte`, `servizi`): card gruppo
  (delta comfort/eco + calendario), card calendario 7x24 e una card per
  ogni stanza (climate, temp salvata, peso, inclusione, modalità, rinnovo).

## Card calendario 7x24

La card `climaoro-calendario` (risorsa `/local/climaoro/climaoro-calendario.js`)
mostra il calendario del gruppo con **righe = 24 ore** e **colonne = 7 giorni**
(orientamento trasposto: ~250px, resta dentro la card senza scroll).
Serve `gruppo` (giorno/notte/servizi) ed `entity` (il sensor
`climaoro_<gruppo>_calendario`). Un click fa ciclare la cella
eco -> comfort -> autonomo via `climaoro.set_calendario`.

## Refresh configurazione immediato

Quando cambiano le options (delta, peso, inclusione, attivo, calendario)
l'integrazione emette l'evento `climaoro_config_updated`; l'app AppDaemon
lo ascolta e rilegge subito `/api/climaoro/config`, senza attendere il
refresh periodico (`refresh_sec` resta come fallback).

## Deploy su VM di test (HAOS su VirtualBox)

- Avviare la VM: `VBoxManage startvm "Home Assistant" --type headless`.
- Accesso SSH: `root@127.0.0.1:2222` (port-forward NAT verso porta 22)
  con chiave `sshkeys/id_climaoro` (non committata nel repo).
- Copiare la card aggiornata **in entrambe** le posizioni:
  ```
  scp -P 2222 .../www/climaoro-calendario.js root@127.0.0.1:/homeassistant/custom_components/climaoro/www/
  scp -P 2222 .../www/climaoro-calendario.js root@127.0.0.1:/homeassistant/www/climaoro/
  ```
  La prima è la sorgente (ri-copiata su ogni setup), la seconda è la
  risorsa servita da `/local/climaoro/climaoro-calendario.js`.
- HTTP di verifica: `http://127.0.0.1:8080/local/climaoro/climaoro-calendario.js`
  (il 8080 è il port-forward NAT verso la porta 80 di HA).

## Test senza dispositivi reali (HA virtuale)

Il climate simulato su HA 2026.8 usa la piattaforma standard
`generic_thermostat` (il template climate è stato rimosso da HA 2026.6):

- `input_number`/`input_boolean`/`input_button` per temp salvata/attuale,
  modalità, heater, rinnovo.
- Template `number`/`sensor`/`switch`/`button` che replicano i nomi reali
  dei termostati.
- `climate: !include sim_climate.yaml` con `generic_thermostat`
  (heater = input_boolean, target_sensor = sensor template).

Poi si manipolano i valori sim e si verificano i log dell'app (cicli,
fascia, guardia/lavoro, priorità, soglia pesi, emergenza). Vedi
`PERCORSO.txt` -> "STATO ATTUALE" per l'esito dei test end-to-end.

> Nota: sulla VM di produzione il simulatore è stato **rimosso**
> (include `sim_*.yaml` tolti da `configuration.yaml` + entità pulite dal
> registry) — i test si fanno in un'installazione separata o riattivando
> gli include.

## Repository

- `PERCORSO.txt`: sintesi aggiornata del progetto (obiettivo,
  architettura, decisioni, stato, prossimi passi) - LEGGERE PRIMA.
- `appdaemon/riscaldamento.py` e `generatore.py`: legacy architettura v1
  (conservati come riferimento, non usati).
- `test/simulazione.yaml` e `ha_config/`: esempi legacy.
