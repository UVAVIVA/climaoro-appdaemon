"""Costanti per l'integrazione Climaoro."""

from __future__ import annotations

import copy
from typing import Final

DOMAIN: Final = "climaoro"
NAME: Final = "Climaoro"

# Evento emesso quando le options della config entry cambiano: l'app
# AppDaemon lo ascolta per rileggere /api/climaoro/config all'istante
# (senza attendere il refresh periodico).
EVENT_CONFIG_UPDATED: Final = f"{DOMAIN}_config_updated"

PLATFORMS: Final = ["number", "switch", "sensor"]

# Gruppi fissi con nomi guida (slug -> etichetta).
GROUP_GIORNO: Final = "giorno"
GROUP_NOTTE: Final = "notte"
GROUP_SERVIZI: Final = "servizi"
GROUPS: Final = [GROUP_GIORNO, GROUP_NOTTE, GROUP_SERVIZI]
GROUP_LABELS: Final = {
    GROUP_GIORNO: "GIORNO",
    GROUP_NOTTE: "NOTTE",
    GROUP_SERVIZI: "SERVIZI",
}

# Chiavi della configurazione (config entry options).
CONF_GLOBAL: Final = "global"
CONF_GROUPS: Final = "groups"
CONF_ROOMS: Final = "rooms"

# Dimensione "appartamento": ogni appartamento ha il proprio globale
# (attivo + soglia pesi) e le proprie copie dei gruppi (calendari/delta).
CONF_APPARTAMENTI: Final = "appartamenti"
CONF_APPARTAMENTO: Final = "appartamento"

# Id del primo appartamento (conserva i unique_id storici per continuita').
APPARTAMENTO_CASA: Final = "casa"
APPARTAMENTO_SECONDO: Final = "appartamento"

CONF_ATTIVO: Final = "attivo"
CONF_SOGLIA_PESI: Final = "soglia_pesi"

CONF_DELTA_COMFORT: Final = "delta_comfort"
CONF_DELTA_ECO: Final = "delta_eco"
CONF_CALENDAR: Final = "calendar"

CONF_ID: Final = "id"
CONF_NOME: Final = "nome"

APPARTAMENTI_DEFAULT: Final = [
    {CONF_ID: APPARTAMENTO_CASA, CONF_NOME: "Casa"},
    {CONF_ID: APPARTAMENTO_SECONDO, CONF_NOME: "Appartamento"},
]

CONF_GRUPPO: Final = "gruppo"
CONF_CLIMA: Final = "clima"
CONF_TEMP_SALVATA: Final = "temp_salvata"
CONF_MODALITA: Final = "modalita"
CONF_RINNOVO: Final = "rinnovo"
CONF_PESO: Final = "peso"
CONF_INCLUSIONE: Final = "inclusione"

# Unique_id delle entita' scelte dall'utente (per risoluzione rename-proof).
CONF_CLIMA_UID: Final = "clima_uid"
CONF_TEMP_SALVATA_UID: Final = "temp_salvata_uid"
CONF_MODALITA_UID: Final = "modalita_uid"
CONF_RINNOVO_UID: Final = "rinnovo_uid"

# Valori del calendario.
VALUE_ECO: Final = "eco"
VALUE_COMFORT: Final = "comfort"
VALUE_AUTONOMO: Final = "autonomo"
CALENDAR_VALUES: Final = [VALUE_ECO, VALUE_COMFORT, VALUE_AUTONOMO]

# Giorni della settimana (ordine del calendario).
DAYS: Final = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
DAY_LABELS: Final = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]

# Default.
DEFAULT_ATTIVO: Final = True
DEFAULT_SOGLIA_PESI: Final = 5.0
DEFAULT_DELTA_COMFORT: Final = 0.5
DEFAULT_DELTA_ECO: Final = 1.0
DEFAULT_PESO: Final = 1.0
DEFAULT_INCLUSIONE: Final = True

# Limiti helper.
# I delta (eco/comfort) si SOTTRAGGONO sempre a temp_salvata per
# definire la guardia; il tetto di riscaldamento resta temp_salvata.
DELTA_MIN: Final = 0.0
DELTA_COMFORT_MAX: Final = 1.0
DELTA_ECO_MAX: Final = 2.0
DELTA_STEP: Final = 0.1
SOGLIA_MIN: Final = 0.0
SOGLIA_MAX: Final = 20.0
SOGLIA_STEP: Final = 0.5
PESO_MIN: Final = 0.0
PESO_MAX: Final = 10.0
PESO_STEP: Final = 0.1

# Fasce di default del calendario (concetto guida, modificabili).
DEFAULT_HOURS: Final = range(0, 24)
DEFAULT_FASCIA_GIORNO_INIZIO: Final = 7
DEFAULT_FASCIA_GIORNO_FINE: Final = 20


def default_groups(gruppi_attivi: list[str]) -> dict[str, dict]:
    """Gruppi con delta e calendario di default."""
    return {
        g: {
            "delta_comfort": DEFAULT_DELTA_COMFORT,
            "delta_eco": DEFAULT_DELTA_ECO,
            CONF_CALENDAR: default_calendar(g),
        }
        for g in GROUPS
        if g in gruppi_attivi
    }


def default_calendar(mode: str) -> dict[str, list[str]]:
    """Calendario di default per un gruppo.

    concept: giorno -> comfort di giorno / eco di notte;
    notte -> il contrario; servizi -> sempre eco.
    """
    calendario: dict[str, list[str]] = {}
    for _day in DAYS:
        ore: list[str] = []
        for ora in DEFAULT_HOURS:
            if mode == GROUP_GIORNO:
                giorno = DEFAULT_FASCIA_GIORNO_INIZIO <= ora < DEFAULT_FASCIA_GIORNO_FINE
                ore.append(VALUE_COMFORT if giorno else VALUE_ECO)
            elif mode == GROUP_NOTTE:
                giorno = DEFAULT_FASCIA_GIORNO_INIZIO <= ora < DEFAULT_FASCIA_GIORNO_FINE
                ore.append(VALUE_ECO if giorno else VALUE_COMFORT)
            else:
                ore.append(VALUE_ECO)
        calendario[_day] = ore
    return calendario


def default_appartamenti(gruppi_attivi: list[str]) -> list[dict]:
    """Appartamenti di default (Casa + Appartamento) con gruppi pronti.

    Il secondo appartamento parte come COPIA indipendente del primo
    (stessa struttura iniziale, poi modificabile a parte).
    """
    base = default_groups(gruppi_attivi)
    apps: list[dict] = []
    for i, cfg in enumerate(APPARTAMENTI_DEFAULT):
        apps.append(
            {
                CONF_ID: cfg[CONF_ID],
                CONF_NOME: cfg[CONF_NOME],
                CONF_ATTIVO: DEFAULT_ATTIVO,
                CONF_SOGLIA_PESI: DEFAULT_SOGLIA_PESI,
                CONF_GROUPS: base if i == 0 else copy.deepcopy(base),
            }
        )
    return apps


def entity_uid(appartamento: str, *parts: str) -> str:
    """Unique_id di un'entita' Climaoro, distinto per appartamento.

    Il primo appartamento ('casa') conserva i unique_id storici
    (climaoro_attivo, climaoro_peso_<stanza>, ...) cosi' le entita'
    e la dashboard esistenti restano identiche; gli altri appartamenti
    usano un prefisso (climaoro_<appartamento>_...).
    """
    base = "_".join(parts)
    if appartamento == APPARTAMENTO_CASA:
        return f"{DOMAIN}_{base}"
    return f"{DOMAIN}_{appartamento}_{base}"


def entity_name_prefix(appartamento: str, nome: str) -> str:
    """Prefisso del nome entita': vuoto per 'casa', '<nome> ' per gli altri."""
    if appartamento == APPARTAMENTO_CASA:
        return ""
    return f"{nome} "


def migrate_options(options: dict) -> dict:
    """Porta le options al formato multi-appartamento (idempotente).

    Da: {attivo, soglia_pesi, groups, rooms}
    A:  {appartamenti: [{id, nome, attivo, soglia_pesi, groups}, ...], rooms}
    Le stanze ricevono il campo 'appartamento' (default 'casa').
    """
    if CONF_APPARTAMENTI in options:
        return options

    groups = options.get(CONF_GROUPS, {})
    apps = []
    for i, cfg in enumerate(APPARTAMENTI_DEFAULT):
        apps.append(
            {
                CONF_ID: cfg[CONF_ID],
                CONF_NOME: cfg[CONF_NOME],
                CONF_ATTIVO: options.get(CONF_ATTIVO, DEFAULT_ATTIVO),
                CONF_SOGLIA_PESI: options.get(CONF_SOGLIA_PESI, DEFAULT_SOGLIA_PESI),
                CONF_GROUPS: groups if i == 0 else copy.deepcopy(groups),
            }
        )

    rooms = []
    for r in options.get(CONF_ROOMS, []):
        rr = dict(r)
        rr.setdefault(CONF_APPARTAMENTO, APPARTAMENTO_CASA)
        rooms.append(rr)

    return {CONF_APPARTAMENTI: apps, CONF_ROOMS: rooms}
