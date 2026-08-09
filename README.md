# CLIMAORO - Integrazione HA (AppDaemon)

Gestione centralizzata del riscaldamento CLIMAORO per Home Assistant.

La logica sta nei termostati (autonomia locale). Questa integrazione permette la
**gestione centralizzata**: AppDaemon disabilita la funzione autonoma dei
termostati e li pilota collettivamente (1 gruppo, 2 fasce, delta per-zona x fascia).

## Struttura

```
appdaemon/
  riscaldamento.py        App AppDaemon (logica centralizzata)
  apps.yaml                Configurazione dell'app (da generare)
generatore.py              Genera apps.yaml + configuration.yaml + lovelace
                          da UN PAIO DI ENTITY DI ESEMPIO
ha_config/                 Esempio generato (2 zone, tag "a")
test/simulazione.yaml      Entita' finte per testare senza dispositivi reali
```

## Il generatore

Da due entity di esempio ricostruisce tutto (tutte le zone, helper, template
"Coerenza", dashboard), senza sapere niente di zone/fasce.

```
python generatore.py \
  --clima climate.termostato_autonomo_1_climatizzazione \
  --temp  number.termostato_autonomo_1_temperatura_salvata \
  --zone  2 \
  --tag   a \
  --feedback binary_sensor.collettore_6_zone_feedback_zona_1
```

Output (in `--outdir`, default `OUT_GENERATORE`):

- `apps.yaml`        blocco istanza AppDaemon (da aggiungere ad apps.yaml)
- `configuration.yaml` input helper + template "Coerenza zona" (da aggiungere a
  configuration.yaml di HA)
- `lovelace.yaml`    card per zona (da incollare in una dashboard)

Le entity dei termostati seguono il pattern del firmware:

- `climate.<dev>_climatizzazione`
- `number.<dev>_temperatura_salvata`
- `switch.<dev>_modalita_centralizzata`
- `button.<dev>_rinnova_modalita_centralizzata`
- `sensor.<dev>_ultimo_messaggio_esp_now`

## Installazione

1. Su HA installare l'addon **AppDaemon**.
2. Copiare `appdaemon/riscaldamento.py` in `<appdaemon>/apps/`.
3. Generare e incollare `apps.yaml` (in `<appdaemon>/apps/apps.yaml`) e il blocco
   `configuration.yaml` (in `configuration.yaml` di HA).
4. Riavviare AppDaemon.

## Test senza dispositivi reali (HA virtuale)

1. Creare un'HA virtuale (vedi sotto).
2. Incollare in `configuration.yaml`: blocco generato + `test/simulazione.yaml`.
3. Far partire AppDaemon con `apps.yaml` generato.
4. Manipolare `input_number.sim_temp1` / `sim_temp2` e verificare i log
   dell'app.

Nota: `riscaldamento.py` deve leggere `hvac_mode`/`current_temperature`/
`temperature`/`hvac_action` dal climate e i parametri dagli helper `input_*`.
