"""Entita' di tipo switch per Climaoro."""

from __future__ import annotations

import copy
from typing import Any

from homeassistant import config_entries
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    APPARTAMENTO_CASA,
    CONF_APPARTAMENTI,
    CONF_APPARTAMENTO,
    CONF_ATTIVO,
    CONF_GROUPS,
    CONF_ID,
    CONF_INCLUSIONE,
    CONF_NOME,
    CONF_ROOMS,
    DOMAIN,
    entity_name_prefix,
    entity_uid,
)

from . import fire_config_updated, get_apartment, get_rooms


class _SwitchEntityBase(SwitchEntity):
    _attr_should_poll = False
    _attr_icon = "mdi:toggle-switch"

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._entry: config_entries.ConfigEntry = hass.config_entries.async_entries(DOMAIN)[0]

    def _update_entry(self, options: dict) -> None:
        self._hass.config_entries.async_update_entry(self._entry, options=options)
        self._entry = self._hass.config_entries.async_entries(DOMAIN)[0]
        fire_config_updated(self._hass)


class Attivo(_SwitchEntityBase):
    """Interruttore master di un appartamento."""

    _attr_icon = "mdi:power"

    def __init__(self, hass: HomeAssistant, app_id: str, nome: str) -> None:
        super().__init__(hass)
        self._app_id = app_id
        self._attr_unique_id = entity_uid(app_id, CONF_ATTIVO)
        self._attr_name = f"Climaoro {entity_name_prefix(app_id, nome)}Attivo"

    @property
    def is_on(self) -> bool | None:
        ap = get_apartment(self.hass, self._app_id)
        if ap is None:
            return None
        return bool(ap.get(CONF_ATTIVO))

    async def _set(self, value: bool) -> None:
        options = copy.deepcopy(dict(self._entry.options))
        appartamenti = list(options.get(CONF_APPARTAMENTI, []))
        for ap in appartamenti:
            if ap.get(CONF_ID) == self._app_id:
                ap[CONF_ATTIVO] = value
                break
        options[CONF_APPARTAMENTI] = appartamenti
        self._update_entry(options)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)


class InclusioneStanza(_SwitchEntityBase):
    """Inclusione di una stanza nella centralizzazione del gruppo."""

    _attr_icon = "mdi:check-decagram"

    def __init__(self, hass: HomeAssistant, app_id: str, nome: str, room_id: str, room_nome: str) -> None:
        super().__init__(hass)
        self._app_id = app_id
        self._room_id = room_id
        self._attr_unique_id = entity_uid(app_id, CONF_INCLUSIONE, room_id)
        self._attr_name = (
            f"Climaoro {entity_name_prefix(app_id, nome)}Inclusione {room_nome}"
        )

    @property
    def is_on(self) -> bool | None:
        for room in get_rooms(self.hass):
            if room.get("id") == self._room_id:
                return bool(room.get(CONF_INCLUSIONE))
        return None

    async def _set(self, value: bool) -> None:
        options = copy.deepcopy(dict(self._entry.options))
        rooms = list(options.get(CONF_ROOMS, []))
        for room in rooms:
            if room.get("id") == self._room_id:
                room[CONF_INCLUSIONE] = value
                break
        options[CONF_ROOMS] = rooms
        self._update_entry(options)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configura le entita' switch."""
    entities: list[SwitchEntity] = []
    for ap in entry.options.get(CONF_APPARTAMENTI, []):
        app_id = ap.get(CONF_ID, APPARTAMENTO_CASA)
        nome = ap.get(CONF_NOME, app_id)
        entities.append(Attivo(hass, app_id, nome))
    for room in entry.options.get(CONF_ROOMS, []):
        app_id = room.get(CONF_APPARTAMENTO, APPARTAMENTO_CASA)
        ap = get_apartment(hass, app_id)
        nome = ap.get(CONF_NOME, app_id) if ap else app_id
        entities.append(
            InclusioneStanza(hass, app_id, nome, room["id"], room.get("nome", room["id"]))
        )
    async_add_entities(entities)
