"""Sensori per Climaoro: calendario 7x24 di ogni gruppo."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from datetime import datetime

from .const import (
    CONF_CALENDAR,
    DAY_LABELS,
    DAYS,
    DOMAIN,
    GROUP_LABELS,
    VALUE_ECO,
)
from . import get_group


class CalendarSensor(SensorEntity):
    """Sensore che espone il calendario 7x24 di un gruppo."""

    _attr_should_poll = False
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, hass: HomeAssistant, gruppo: str) -> None:
        self.hass = hass
        self._gruppo = gruppo
        self._attr_unique_id = f"{DOMAIN}_calendario_{gruppo}"
        self._attr_name = f"Climaoro Calendario {GROUP_LABELS[gruppo]}"
        hass.data.setdefault(DOMAIN, {}).setdefault("sensors", {})[gruppo] = self

    @property
    def native_value(self) -> str:
        """Stato corrente: modalita' dell'ora attuale."""
        calendario = self._calendario()
        oggi = DAYS[datetime.now().weekday()]
        ora = datetime.now().hour
        return calendario.get(oggi, [VALUE_ECO] * 24)[ora]

    def _calendario(self) -> dict[str, list[str]]:
        group = get_group(self.hass, self._gruppo)
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
            "ore": list(range(24)),
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configura i sensori."""
    async_add_entities(
        CalendarSensor(hass, gruppo) for gruppo in entry.options.get("groups", {})
    )
