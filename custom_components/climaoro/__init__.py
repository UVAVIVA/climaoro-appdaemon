"""Integrazione Climaoro - gestione centralizzata termostati autonomi."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
import voluptuous as vol

from .const import (
    APPARTAMENTO_CASA,
    CONF_APPARTAMENTI,
    CONF_APPARTAMENTO,
    CONF_ATTIVO,
    CONF_CALENDAR,
    CONF_CLIMA,
    CONF_CLIMA_UID,
    CONF_DELTA_COMFORT,
    CONF_DELTA_ECO,
    CONF_GROUPS,
    CONF_GRUPPO,
    CONF_ID,
    CONF_INCLUSIONE,
    CONF_MODALITA,
    CONF_MODALITA_UID,
    CONF_NOME,
    CONF_PESO,
    CONF_RINNOVO,
    CONF_RINNOVO_UID,
    CONF_ROOMS,
    CONF_SOGLIA_PESI,
    CONF_TEMP_SALVATA,
    CONF_TEMP_SALVATA_UID,
    DOMAIN,
    EVENT_CONFIG_UPDATED,
    GROUP_LABELS,
    GROUPS,
    VALUE_AUTONOMO,
    VALUE_COMFORT,
    VALUE_ECO,
    default_calendar,
    entity_uid,
    migrate_options,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SWITCH, Platform.SENSOR]


def get_data(hass: HomeAssistant) -> dict[str, Any]:
    """Dati di configurazione (appartamenti + stanze), forma migrata."""
    entry = _get_entry(hass)
    if entry is None:
        return {}
    return migrate_options(entry.data.get("data") or entry.options)


def _get_entry(hass: HomeAssistant) -> ConfigEntry | None:
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


def fire_config_updated(hass: HomeAssistant) -> None:
    """Notifica l'app AppDaemon che la config runtime e' cambiata.

    Safe da qualsiasi contesto (usa la variante sync del bus).
    """
    hass.bus.fire(EVENT_CONFIG_UPDATED)


def get_appartamenti(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Lista degli appartamenti configurati."""
    return list(get_data(hass).get(CONF_APPARTAMENTI, []))


def get_apartment(hass: HomeAssistant, app_id: str) -> dict[str, Any] | None:
    """Appartamento per id."""
    for ap in get_appartamenti(hass):
        if ap.get(CONF_ID) == app_id:
            return ap
    return None


def get_group(hass: HomeAssistant, app_id: str, gruppo: str) -> dict[str, Any] | None:
    """Configurazione di un gruppo (delta + calendario) di un appartamento."""
    ap = get_apartment(hass, app_id)
    if ap is None:
        return None
    return ap.get(CONF_GROUPS, {}).get(gruppo)


def get_rooms(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Lista delle stanze configurate."""
    return list(get_data(hass).get(CONF_ROOMS, []))


def get_room(hass: HomeAssistant, room_id: str) -> dict[str, Any] | None:
    """Stanza per id."""
    for room in get_rooms(hass):
        if room.get("id") == room_id:
            return room
    return None


async def build_runtime_config(hass: HomeAssistant) -> dict[str, Any]:
    """Configurazione runtime con gli entity_id correnti (risolti dal registry).

    App Daemon e pannello frontend usano SOLO questo: nessun entity_id
    hardcoded. Se l'utente rinomina un'entita' nella UI, il registry
    restituisce l'entity_id aggiornato.

    Formato: {"appartamenti": [{"id", "nome", "attivo", "soglia_pesi",
    "entities", "gruppi": [...]}], "entities": {unique_id: entity_id}}.
    """
    entry = _get_entry(hass)
    if entry is None:
        return {"appartamenti": [], "entities": {}}

    data = get_data(hass)
    reg: er.EntityRegistry = er.async_get(hass)

    # Mappa unique_id -> entity_id per tutte le entita' generate da Climaoro.
    eid_by_uid: dict[str, str] = {}
    for e in reg.entities.values():
        if e.platform == DOMAIN and e.entity_id:
            eid_by_uid[e.unique_id] = e.entity_id

    def eid(uid: str) -> str | None:
        return eid_by_uid.get(uid)

    def resolve_user(entity_id: str | None, unique_id: str | None) -> str | None:
        if unique_id:
            for e in reg.entities.values():
                if e.unique_id == unique_id and e.entity_id:
                    return e.entity_id
        return entity_id

    def room_ap(r: dict[str, Any]) -> str:
        return r.get(CONF_APPARTAMENTO, APPARTAMENTO_CASA)

    rooms = list(data.get(CONF_ROOMS, []))
    appartamenti: list[dict[str, Any]] = []
    for ap in data.get(CONF_APPARTAMENTI, []):
        ap_id = ap.get(CONF_ID, APPARTAMENTO_CASA)
        ap_nome = ap.get(CONF_NOME, ap_id)

        global_info = {
            CONF_ATTIVO: bool(ap.get(CONF_ATTIVO)),
            CONF_SOGLIA_PESI: ap.get(CONF_SOGLIA_PESI),
            "entities": {
                CONF_ATTIVO: eid(entity_uid(ap_id, CONF_ATTIVO)),
                CONF_SOGLIA_PESI: eid(entity_uid(ap_id, CONF_SOGLIA_PESI)),
            },
        }

        gruppi_info: list[dict[str, Any]] = []
        for gruppo, group in ap.get(CONF_GROUPS, {}).items():
            stanze = [
                {
                    "id": r.get("id"),
                    CONF_NOME: r.get(CONF_NOME),
                    CONF_GRUPPO: r.get(CONF_GRUPPO),
                    CONF_PESO: r.get(CONF_PESO),
                    CONF_INCLUSIONE: bool(r.get(CONF_INCLUSIONE, True)),
                    "entities": {
                        CONF_CLIMA: resolve_user(r.get(CONF_CLIMA), r.get(CONF_CLIMA_UID)),
                        CONF_TEMP_SALVATA: resolve_user(
                            r.get(CONF_TEMP_SALVATA), r.get(CONF_TEMP_SALVATA_UID)
                        ),
                        CONF_MODALITA: resolve_user(r.get(CONF_MODALITA), r.get(CONF_MODALITA_UID)),
                        CONF_RINNOVO: resolve_user(r.get(CONF_RINNOVO), r.get(CONF_RINNOVO_UID)),
                        CONF_PESO: eid(entity_uid(ap_id, CONF_PESO, r.get("id"))),
                        CONF_INCLUSIONE: eid(entity_uid(ap_id, CONF_INCLUSIONE, r.get("id"))),
                    },
                }
                for r in rooms
                if r.get(CONF_GRUPPO) == gruppo and room_ap(r) == ap_id
            ]
            gruppi_info.append(
                {
                    "id": gruppo,
                    "label": GROUP_LABELS.get(gruppo, gruppo),
                    CONF_DELTA_COMFORT: group.get(CONF_DELTA_COMFORT),
                    CONF_DELTA_ECO: group.get(CONF_DELTA_ECO),
                    CONF_CALENDAR: group.get(CONF_CALENDAR),
                    "entities": {
                        CONF_DELTA_COMFORT: eid(entity_uid(ap_id, "delta", gruppo, CONF_DELTA_COMFORT)),
                        CONF_DELTA_ECO: eid(entity_uid(ap_id, "delta", gruppo, CONF_DELTA_ECO)),
                        "calendario": eid(entity_uid(ap_id, "calendario", gruppo)),
                    },
                    "stanze": stanze,
                }
            )

        appartamenti.append(
            {
                "id": ap_id,
                "nome": ap_nome,
                **global_info,
                "gruppi": gruppi_info,
            }
        )

    return {
        "appartamenti": appartamenti,
        "entities": eid_by_uid,
    }


@websocket_api.websocket_command({vol.Required("type"): "climaoro/config"})
@websocket_api.ws_require_user()
@websocket_api.async_response
async def _ws_config(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Websocket: config runtime generica."""
    connection.send_result(msg["id"], await build_runtime_config(hass))


class ClimaoroConfigView(HomeAssistantView):
    """Endpoint REST /api/climaoro/config."""

    url = "/api/climaoro/config"
    name = "api:climaoro:config"
    requires_auth = True

    async def get(self, request):
        hass: HomeAssistant = request.app["hass"]
        return self.json(await build_runtime_config(hass))


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Registra endpoint REST e websocket (una sola volta)."""
    websocket_api.async_register_command(hass, _ws_config)
    hass.http.register_view(ClimaoroConfigView())
    try:
        await hass.async_add_executor_job(_copy_www, hass)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Copia file www fallita: %s", err)
    return True


def _copy_www(hass: HomeAssistant) -> None:
    """Copia i file frontend in config/www (serviti su /local)."""
    src_dir = Path(__file__).parent / "www"
    if not src_dir.exists():
        return
    dest_dir = Path(hass.config.path("www")) / "climaoro"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for src in src_dir.iterdir():
        if not src.is_file():
            continue
        dest = dest_dir / src.name
        dest.write_bytes(src.read_bytes())


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migra la config entry dal formato v1 (globale unico) a v2 (appartamenti)."""
    if entry.version > 2:
        return False
    if entry.version == 1:
        raw = entry.data.get("data") or dict(entry.options)
        migrated = migrate_options(dict(raw))
        hass.config_entries.async_update_entry(
            entry, data={}, options=migrated, version=2
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura l'integrazione da una config entry."""
    if entry.data.get("data"):
        hass.config_entries.async_update_entry(
            entry, data={}, options=entry.data["data"]
        )

    migrated = migrate_options(dict(entry.options))
    if migrated != dict(entry.options):
        hass.config_entries.async_update_entry(entry, options=migrated)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"entry": entry}
    _register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _run_provision() -> None:
        """Provisioning automatico dopo il setup (AppDaemon + dashboard)."""
        from . import provision

        try:
            results = await provision.async_provision(hass, entry)
            for line in results:
                _LOGGER.warning("Climaoro provision: %s", line)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Climaoro provision fallita: %s", err)

    entry.async_create_task(hass, _run_provision())
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Rimuove l'integrazione."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


def async_update_group_calendar(
    hass: HomeAssistant,
    entry: ConfigEntry,
    app_id: str,
    gruppo: str,
    calendario: dict[str, list[str]],
) -> None:
    """Salva il calendario di un gruppo (di un appartamento) nella config entry."""
    options = dict(entry.options)
    appartamenti = list(options.get(CONF_APPARTAMENTI, []))
    for ap in appartamenti:
        if ap.get(CONF_ID) != app_id:
            continue
        groups = dict(ap.get(CONF_GROUPS, {}))
        group = dict(groups.get(gruppo, {}))
        group[CONF_CALENDAR] = calendario
        groups[gruppo] = group
        ap[CONF_GROUPS] = groups
        break
    options[CONF_APPARTAMENTI] = appartamenti
    hass.config_entries.async_update_entry(entry, options=options)
    fire_config_updated(hass)


def _register_services(hass: HomeAssistant) -> None:
    """Registra i servizi dell'integrazione."""

    async def set_calendario(call: ServiceCall) -> None:
        """Imposta una cella del calendario di un gruppo (di un appartamento).

        Parametri: appartamento, gruppo, giorno, ora, valore.
        """
        entry = _get_entry(hass)
        if entry is None:
            return
        app_id = call.data.get("appartamento", APPARTAMENTO_CASA)
        gruppo = call.data["gruppo"]
        giorno = call.data["giorno"]
        ora = int(call.data["ora"])
        valore = call.data["valore"]

        group = get_group(hass, app_id, gruppo)
        if group is None:
            _LOGGER.error(
                "Appartamento '%s' / gruppo '%s' non configurato", app_id, gruppo
            )
            return

        calendario = dict(group.get(CONF_CALENDAR, default_calendar(gruppo)))
        ore = list(calendario.get(giorno, [VALUE_ECO] * 24))
        if 0 <= ora < 24:
            ore[ora] = valore
        calendario[giorno] = ore

        async_update_group_calendar(hass, entry, app_id, gruppo, calendario)

        sensors = hass.data.get(DOMAIN, {}).get("sensors", {})
        sensor = sensors.get((app_id, gruppo))
        if sensor is not None:
            sensor.async_write_ha_state()

    hass.services.async_register(
        DOMAIN,
        "set_calendario",
        set_calendario,
        schema=vol.Schema(
            {
                vol.Optional("appartamento", default=APPARTAMENTO_CASA): str,
                vol.Required("gruppo"): vol.In(GROUPS),
                vol.Required("giorno"): str,
                vol.Required("ora"): int,
                vol.Required("valore"): vol.In([VALUE_ECO, VALUE_COMFORT, VALUE_AUTONOMO]),
            }
        ),
    )

    async def provisiona(call: ServiceCall) -> None:
        """Riesegue il provisioning completo (AppDaemon + dashboard)."""
        from . import provision

        entry = _get_entry(hass)
        if entry is None:
            _LOGGER.error("Nessuna config entry Climaoro attiva")
            return
        results = await provision.async_provision(hass, entry)
        for line in results:
            _LOGGER.warning("Climaoro provisiona: %s", line)

    hass.services.async_register(
        DOMAIN,
        "provisiona",
        provisiona,
        schema=vol.Schema({}),
    )
