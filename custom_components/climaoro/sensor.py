"""Sensori per Climaoro: calendario 7x24 di ogni gruppo (per appartamento)."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from datetime import datetime

from .const import (
    APPARTAMENTO_CASA,
    CONF_APPARTAMENTI,
    CONF_CALENDAR,
    CONF_GROUPS,
    CONF_ID,
    CONF_NOME,
    DAY_LABELS,
    DAYS,
    DOMAIN,
    GROUP_LABELS,
    VALUE_ECO,
    entity_name_prefix,
    entity_uid,
)
from . import get_group


class CalendarSensor(SensorEntity):
    """Sensore che espone il calendario 7x24 di un gruppo (di un appartamento)."""

    _attr_should_poll = False
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, hass: HomeAssistant, app_id: str, nome: str, gruppo: str) -> None:
        self.hass = hass
        self._app_id = app_id
        self._nome = nome
        self._gruppo = gruppo
        self._attr_unique_id = entity_uid(app_id, "calendario", gruppo)
        self._attr_name = (
            f"Climaoro {entity_name_prefix(app_id, nome)}Calendario {GROUP_LABELS[gruppo]}"
        )
        hass.data.setdefault(DOMAIN, {}).setdefault("sensors", {})[(app_id, gruppo)] = self

    @property
    def native_value(self) -> str:
        """Stato corrente: modalita' dell'ora attuale."""
        calendario = self._calendario()
        oggi = DAYS[datetime.now().weekday()]
        ora = datetime.now().hour
        return calendario.get(oggi, [VALUE_ECO] * 24)[ora]

    def _calendario(self) -> dict[str, list[str]]:
        group = get_group(self.hass, self._app_id, self._gruppo)
        if group is None:
            return {day: [VALUE_ECO] * 24 for day in DAYS}
        return group.get(CONF_CALENDAR, {})

    @property
    def extra_state_attributes(self) -> dict:
        """Calendario completo negli attributi."""
        return {
            "calendario": self._calendario(),
            "giorni": DAY_LABELS,
            "giorni_slug": DAYS,
            "gruppo": GROUP_LABELS[self._gruppo],
            "appartamento": self._app_id,
            "appartamento_nome": self._nome,
            "ore": list(range(24)),
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configura i sensori."""
    entities: list[SensorEntity] = []
    for ap in entry.options.get(CONF_APPARTAMENTI, []):
        app_id = ap.get(CONF_ID, APPARTAMENTO_CASA)
        nome = ap.get(CONF_NOME, app_id)
        for gruppo in ap.get(CONF_GROUPS, {}):
            entities.append(CalendarSensor(hass, app_id, nome, gruppo))
    async_add_entities(entities)
