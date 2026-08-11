"""Entita' di tipo switch per Climaoro."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ATTIVO,
    CONF_INCLUSIONE,
    CONF_ROOMS,
    DOMAIN,
)

from . import fire_config_updated, get_data, get_rooms


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
    """Interruttore master."""

    _attr_unique_id = f"{DOMAIN}_attivo"
    _attr_name = "Climaoro Attivo"
    _attr_icon = "mdi:power"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass)

    @property
    def is_on(self) -> bool | None:
        return bool(get_data(self.hass).get(CONF_ATTIVO))

    async def async_turn_on(self, **kwargs) -> None:
        options = dict(self._entry.options)
        options[CONF_ATTIVO] = True
        self._update_entry(options)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        options = dict(self._entry.options)
        options[CONF_ATTIVO] = False
        self._update_entry(options)
        self.async_write_ha_state()


class InclusioneStanza(_SwitchEntityBase):
    """Inclusione di una stanza nella centralizzazione del gruppo."""

    _attr_icon = "mdi:check-decagram"

    def __init__(self, hass: HomeAssistant, room_id: str, nome: str) -> None:
        super().__init__(hass)
        self._room_id = room_id
        self._attr_unique_id = f"{DOMAIN}_inclusione_{room_id}"
        self._attr_name = f"Climaoro Inclusione {nome}"

    @property
    def is_on(self) -> bool | None:
        for room in get_rooms(self.hass):
            if room.get("id") == self._room_id:
                return bool(room.get(CONF_INCLUSIONE))
        return None

    async def _set(self, value: bool) -> None:
        options = dict(self._entry.options)
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
    entities: list[SwitchEntity] = [Attivo(hass)]
    for room in entry.options.get(CONF_ROOMS, []):
        entities.append(InclusioneStanza(hass, room["id"], room.get("nome", room["id"])))
    async_add_entities(entities)
