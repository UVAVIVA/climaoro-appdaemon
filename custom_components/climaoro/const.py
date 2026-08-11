"""Costanti per l'integrazione Climaoro."""

from __future__ import annotations

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

CONF_ATTIVO: Final = "attivo"
CONF_SOGLIA_PESI: Final = "soglia_pesi"

CONF_DELTA_COMFORT: Final = "delta_comfort"
CONF_DELTA_ECO: Final = "delta_eco"
CONF_CALENDAR: Final = "calendar"

CONF_ID: Final = "id"
CONF_NOME: Final = "nome"
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
DELTA_MIN: Final = -5.0
DELTA_MAX: Final = 5.0
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
