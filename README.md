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

- **Stanze** (2-8): nome, gruppo di appartenenza, **peso** e
  **inclusione** (le uniche cose individuali) + le 4 entità chiave del
  termostato:
  - `climate.<dev>_climatizzazione`
  - `number.<dev>_temperatura_salvata`
  - `switch.<dev>_modalita_centralizzata`
  - `button.<dev>_rinnovo_modalita_centralizzata`
- **Gruppi** fissi GIORNO / NOTTE / SERVIZI (opzionali). Ognuno ha:
  - 2 **delta** (comfort, eco)
  - un **calendario 7x24** con tendina `eco` / `comfort` / `autonomo`
    (autonomo = i termostati del gruppo tornano al firmware)
  - `number.climaoro_<gruppo>_delta_comfort` / `_delta_eco`
  - `sensor.climaoro_<gruppo>_calendario`
- **Globale**: `switch.climaoro_attivo` (master) + `number.climaoro_soglia_pesi`.

### Logica di controllo (app AppDaemon)

Ogni ciclo (60s), per ogni gruppo in fascia non-autonoma:

1. Calcola **guardia** = temp_salvata - delta e **lavoro** =
   temp_salvata + delta dalla fascia corrente.
2. Allinea il setpoint a guardia e raccoglie le stanze in richiesta
   (temp reale <= temp_salvata - 0.5), sommandone i pesi.
3. Se qualche stanza è già in **riscaldamento** (`hvac_action=heating`):
   priorità a lei, si accendono le richiedenti.
4. Altrimenti, se **totale pesi >= soglia**: accensione collettiva
   (tutte le richiedenti a lavoro).
5. Altrimenti **emergenza individuale**: stanza con temp <= guardia - 0.4
   accesa a lavoro.

Sicurezza: prima di un comando a un climate l'app accende
automaticamente lo `switch.<dev>_modalita_centralizzata` se spento.
Un timer periodico (default 240s) preme il pulsante "rinnovo" delle
stanze incluse (non in fascia autonoma).

## Installazione

1. Copiare `custom_components/climaoro/` in `<config>/custom_components/`
   e riavviare HA.
2. **Aggiungi integrazione -> Climaoro**: il wizard guida nell'inserimento
   delle entità chiave delle stanze; al termine crea le entità di contorno.
3. Installare l'addon **AppDaemon**; copiare `appdaemon/climaoro.py` e
   `appdaemon/apps.yaml` in `<addon_configs>/<id_appdaemon>/apps/`.
4. In `apps.yaml` impostare:
   ```yaml
   climaoro:
     module: climaoro
     class: Climaoro
     ha_url: http://<ip-ha>:80
     ha_token: <token long-lived HA>
   ```
5. Riavviare AppDaemon. Il pannello "Climaoro" è disponibile a
   `/climaoro-panel`.

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

## Repository

- `PERCORSO.txt`: sintesi aggiornata del progetto (obiettivo,
  architettura, decisioni, stato, prossimi passi) - LEGGERE PRIMA.
- `appdaemon/riscaldamento.py` e `generatore.py`: legacy architettura v1
  (conservati come riferimento, non usati).
- `test/simulazione.yaml` e `ha_config/`: esempi legacy.
