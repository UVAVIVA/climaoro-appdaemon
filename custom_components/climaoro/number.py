"""Entita' di tipo number per Climaoro."""

from __future__ import annotations

import copy

from homeassistant import config_entries
from homeassistant.components.number import NumberEntity
from homeassistant.components.number.const import NumberMode
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    APPARTAMENTO_CASA,
    CONF_APPARTAMENTI,
    CONF_APPARTAMENTO,
    CONF_DELTA_ACCENSIONE_COMFORT,
    CONF_DELTA_ACCENSIONE_ECO,
    CONF_DELTA_SPEGNIMENTO_COMFORT,
    CONF_DELTA_SPEGNIMENTO_ECO,
    CONF_GROUPS,
    CONF_ID,
    CONF_NOME,
    CONF_PESO,
    CONF_ROOMS,
    CONF_SOGLIA_PESI,
    DELTA_ACCENSIONE_COMFORT_MAX,
    DELTA_ACCENSIONE_COMFORT_MIN,
    DELTA_ACCENSIONE_ECO_MAX,
    DELTA_ACCENSIONE_ECO_MIN,
    DELTA_SPEGNIMENTO_COMFORT_MAX,
    DELTA_SPEGNIMENTO_COMFORT_MIN,
    DELTA_SPEGNIMENTO_ECO_MAX,
    DELTA_SPEGNIMENTO_ECO_MIN,
    DELTA_STEP,
    DOMAIN,
    GROUP_LABELS,
    PESO_MAX,
    PESO_MIN,
    PESO_STEP,
    SOGLIA_MAX,
    SOGLIA_MIN,
    SOGLIA_STEP,
    entity_name_prefix,
    entity_uid,
)
from . import fire_config_updated, get_apartment, get_group, get_rooms

# Min, max, etichetta e unique_id legacy per ogni campo delta.
DELTA_CAMPI: dict[str, tuple[float, float, str, str]] = {
    CONF_DELTA_ACCENSIONE_COMFORT: (
        DELTA_ACCENSIONE_COMFORT_MIN,
        DELTA_ACCENSIONE_COMFORT_MAX,
        "comfort Accensione",
        "delta_comfort",
    ),
    CONF_DELTA_ACCENSIONE_ECO: (
        DELTA_ACCENSIONE_ECO_MIN,
        DELTA_ACCENSIONE_ECO_MAX,
        "eco Accensione",
        "delta_eco",
    ),
    CONF_DELTA_SPEGNIMENTO_COMFORT: (
        DELTA_SPEGNIMENTO_COMFORT_MIN,
        DELTA_SPEGNIMENTO_COMFORT_MAX,
        "comfort Spegnimento",
        "delta_spegnimento_comfort",
    ),
    CONF_DELTA_SPEGNIMENTO_ECO: (
        DELTA_SPEGNIMENTO_ECO_MIN,
        DELTA_SPEGNIMENTO_ECO_MAX,
        "eco Spegnimento",
        "delta_spegnimento_eco",
    ),
}


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
    """Soglia pesi di un appartamento."""

    _attr_native_min_value = SOGLIA_MIN
    _attr_native_max_value = SOGLIA_MAX
    _attr_native_step = SOGLIA_STEP
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:weight"

    def __init__(self, hass: HomeAssistant, app_id: str, nome: str) -> None:
        super().__init__(hass)
        self._app_id = app_id
        self._attr_unique_id = entity_uid(app_id, CONF_SOGLIA_PESI)
        self._attr_name = f"Climaoro {entity_name_prefix(app_id, nome)}Soglia pesi"

    @property
    def native_value(self) -> float | None:
        ap = get_apartment(self.hass, self._app_id)
        if ap is None:
            return None
        return ap.get(CONF_SOGLIA_PESI)

    async def async_set_native_value(self, value: float) -> None:
        options = copy.deepcopy(dict(self._entry.options))
        appartamenti = list(options.get(CONF_APPARTAMENTI, []))
        for ap in appartamenti:
            if ap.get(CONF_ID) == self._app_id:
                ap[CONF_SOGLIA_PESI] = float(value)
                break
        options[CONF_APPARTAMENTI] = appartamenti
        self._update_entry(options)
        self.async_write_ha_state()


class DeltaGruppo(_BaseNumber, NumberEntity):
    """Delta accensione/spegnimento (comfort/eco) di un gruppo."""

    _attr_native_step = DELTA_STEP
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:thermometer"

    def __init__(self, hass: HomeAssistant, app_id: str, nome: str, gruppo: str, campo: str) -> None:
        super().__init__(hass)
        self._app_id = app_id
        self._gruppo = gruppo
        self._campo = campo
        min_v, max_v, label, uid = DELTA_CAMPI[campo]
        self._attr_native_min_value = min_v
        self._attr_native_max_value = max_v
        self._attr_unique_id = entity_uid(app_id, "delta", gruppo, uid)
        self._attr_name = (
            f"Climaoro {entity_name_prefix(app_id, nome)}"
            f"{GROUP_LABELS[gruppo]} Delta {label}"
        )

    @property
    def native_value(self) -> float | None:
        group = get_group(self.hass, self._app_id, self._gruppo)
        if group is None:
            return None
        return group.get(self._campo)

    async def async_set_native_value(self, value: float) -> None:
        options = copy.deepcopy(dict(self._entry.options))
        appartamenti = list(options.get(CONF_APPARTAMENTI, []))
        for ap in appartamenti:
            if ap.get(CONF_ID) != self._app_id:
                continue
            groups = dict(ap.get(CONF_GROUPS, {}))
            group = dict(groups.get(self._gruppo, {}))
            group[self._campo] = float(value)
            groups[self._gruppo] = group
            ap[CONF_GROUPS] = groups
            break
        options[CONF_APPARTAMENTI] = appartamenti
        self._update_entry(options)
        self.async_write_ha_state()


class PesoStanza(_BaseNumber, NumberEntity):
    """Peso di una stanza."""

    _attr_native_min_value = PESO_MIN
    _attr_native_max_value = PESO_MAX
    _attr_native_step = PESO_STEP
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:scale-balance"

    def __init__(self, hass: HomeAssistant, app_id: str, nome: str, room_id: str, room_nome: str) -> None:
        super().__init__(hass)
        self._app_id = app_id
        self._room_id = room_id
        self._attr_unique_id = entity_uid(app_id, CONF_PESO, room_id)
        self._attr_name = (
            f"Climaoro {entity_name_prefix(app_id, nome)}Peso {room_nome}"
        )

    @property
    def native_value(self) -> float | None:
        for room in get_rooms(self.hass):
            if room.get("id") == self._room_id:
                return room.get(CONF_PESO)
        return None

    async def async_set_native_value(self, value: float) -> None:
        options = copy.deepcopy(dict(self._entry.options))
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
    entities: list[NumberEntity] = []
    for ap in entry.options.get(CONF_APPARTAMENTI, []):
        app_id = ap.get(CONF_ID, APPARTAMENTO_CASA)
        nome = ap.get(CONF_NOME, app_id)
        entities.append(SogliaPesi(hass, app_id, nome))
        for gruppo in ap.get(CONF_GROUPS, {}):
            for campo in DELTA_CAMPI:
                entities.append(DeltaGruppo(hass, app_id, nome, gruppo, campo))
    for room in entry.options.get(CONF_ROOMS, []):
        app_id = room.get(CONF_APPARTAMENTO, APPARTAMENTO_CASA)
        ap = get_apartment(hass, app_id)
        nome = ap.get(CONF_NOME, app_id) if ap else app_id
        entities.append(PesoStanza(hass, app_id, nome, room["id"], room.get("nome", room["id"])))
    async_add_entities(entities)
