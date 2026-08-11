"""Entita' di tipo number per Climaoro."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.components.number import NumberEntity
from homeassistant.components.number.const import NumberMode
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ATTIVO,
    CONF_GRUPPO,
    CONF_PESO,
    CONF_ROOMS,
    CONF_SOGLIA_PESI,
    DELTA_MAX,
    DELTA_MIN,
    DELTA_STEP,
    DOMAIN,
    GROUP_LABELS,
    PESO_MAX,
    PESO_MIN,
    PESO_STEP,
    SOGLIA_MAX,
    SOGLIA_MIN,
    SOGLIA_STEP,
)
from . import fire_config_updated, get_group, get_rooms


class _BaseNumber(NumberEntity):
    _attr_should_poll = False
    _attr_mode = NumberMode.SLIDER

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._entry: config_entries.ConfigEntry = hass.config_entries.async_entries(DOMAIN)[0]

    def _update_entry(self, options: dict) -> None:
        self._hass.config_entries.async_update_entry(self._entry, options=options)
        self._entry = self._hass.config_entries.async_entries(DOMAIN)[0]
        fire_config_updated(self._hass)


class SogliaPesi(_BaseNumber, NumberEntity):
    """Soglia pesi globale."""

    _attr_native_min_value = SOGLIA_MIN
    _attr_native_max_value = SOGLIA_MAX
    _attr_native_step = SOGLIA_STEP
    _attr_mode = NumberMode.SLIDER
    _attr_unique_id = f"{DOMAIN}_soglia_pesi"
    _attr_name = "Climaoro Soglia pesi"
    _attr_icon = "mdi:weight"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass)

    @property
    def native_value(self) -> float | None:
        from . import get_data

        return get_data(self.hass).get(CONF_SOGLIA_PESI)

    async def async_set_native_value(self, value: float) -> None:
        options = dict(self._entry.options)
        options[CONF_SOGLIA_PESI] = float(value)
        self._update_entry(options)
        self.async_write_ha_state()


class DeltaGruppo(_BaseNumber, NumberEntity):
    """Delta comfort/eco di un gruppo."""

    _attr_native_min_value = DELTA_MIN
    _attr_native_max_value = DELTA_MAX
    _attr_native_step = DELTA_STEP
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:thermometer"

    def __init__(self, hass: HomeAssistant, gruppo: str, campo: str) -> None:
        super().__init__(hass)
        self._gruppo = gruppo
        self._campo = campo
        self._attr_unique_id = f"{DOMAIN}_delta_{gruppo}_{campo}"
        self._attr_name = f"Climaoro {GROUP_LABELS[gruppo]} Delta {campo.split('_', 1)[1]}"

    @property
    def native_value(self) -> float | None:
        group = get_group(self.hass, self._gruppo)
        if group is None:
            return None
        return group.get(self._campo)

    async def async_set_native_value(self, value: float) -> None:
        options = dict(self._entry.options)
        groups = dict(options.get("groups", {}))
        group = dict(groups.get(self._gruppo, {}))
        group[self._campo] = float(value)
        groups[self._gruppo] = group
        options["groups"] = groups
        self._update_entry(options)
        self.async_write_ha_state()


class PesoStanza(_BaseNumber, NumberEntity):
    """Peso di una stanza."""

    _attr_native_min_value = PESO_MIN
    _attr_native_max_value = PESO_MAX
    _attr_native_step = PESO_STEP
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:scale-balance"

    def __init__(self, hass: HomeAssistant, room_id: str, nome: str) -> None:
        super().__init__(hass)
        self._room_id = room_id
        self._attr_unique_id = f"{DOMAIN}_peso_{room_id}"
        self._attr_name = f"Climaoro Peso {nome}"

    @property
    def native_value(self) -> float | None:
        for room in get_rooms(self.hass):
            if room.get("id") == self._room_id:
                return room.get(CONF_PESO)
        return None

    async def async_set_native_value(self, value: float) -> None:
        options = dict(self._entry.options)
        rooms = list(options.get(CONF_ROOMS, []))
        for room in rooms:
            if room.get("id") == self._room_id:
                room[CONF_PESO] = float(value)
                break
        options[CONF_ROOMS] = rooms
        self._update_entry(options)
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configura le entita' number."""
    entities: list[NumberEntity] = [SogliaPesi(hass)]
    for gruppo in entry.options.get("groups", {}):
        entities.append(DeltaGruppo(hass, gruppo, "delta_comfort"))
        entities.append(DeltaGruppo(hass, gruppo, "delta_eco"))
    for room in entry.options.get(CONF_ROOMS, []):
        entities.append(PesoStanza(hass, room["id"], room.get("nome", room["id"])))
    async_add_entities(entities)
