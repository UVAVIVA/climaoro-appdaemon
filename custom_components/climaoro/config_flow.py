"""Config flow e options flow per Climaoro."""

from __future__ import annotations

import copy
from typing import Any

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import (
    APPARTAMENTO_CASA,
    APPARTAMENTI_DEFAULT,
    CALENDAR_VALUES,
    CONF_APPARTAMENTI,
    CONF_APPARTAMENTO,
    CONF_ATTIVO,
    CONF_CLIMA,
    CONF_CLIMA_UID,
    CONF_DELTA_ACCENSIONE_COMFORT,
    CONF_DELTA_ACCENSIONE_ECO,
    CONF_DELTA_SPEGNIMENTO_COMFORT,
    CONF_DELTA_SPEGNIMENTO_ECO,
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
    DEFAULT_ATTIVO,
    DEFAULT_DELTA_ACCENSIONE_COMFORT,
    DEFAULT_DELTA_ACCENSIONE_ECO,
    DEFAULT_DELTA_SPEGNIMENTO_COMFORT,
    DEFAULT_DELTA_SPEGNIMENTO_ECO,
    DEFAULT_INCLUSIONE,
    DEFAULT_PESO,
    DEFAULT_SOGLIA_PESI,
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
    GROUPS,
    PESO_MAX,
    PESO_MIN,
    PESO_STEP,
    SOGLIA_MAX,
    SOGLIA_MIN,
    SOGLIA_STEP,
    default_appartamenti,
    migrate_options,
)

GROUP_OPTIONS = [{"value": g, "label": GROUP_LABELS[g]} for g in GROUPS]


def _slug(nome: str) -> str:
    from homeassistant.util import slugify

    return slugify(nome) or "stanza"


def _entity_selector(domains: list[str]):
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domains, multiple=False)
    )


def _numero(minimum: float, maximum: float, step: float, mode: str = "slider"):
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=minimum, max=maximum, step=step, mode=mode)
    )


def _gruppo_selector():
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=GROUP_OPTIONS,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _appartamento_selector(options: dict, appartamenti: list[dict] | None = None):
    """Selettore appartamento (dai dati oppure da una lista esplicita)."""
    apps = (
        appartamenti
        if appartamenti is not None
        else options.get(CONF_APPARTAMENTI, [])
    )
    opt = [
        {"value": ap.get(CONF_ID), "label": ap.get(CONF_NOME, ap.get(CONF_ID))}
        for ap in apps
    ]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=opt,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _nome_app(app_id: str) -> str:
    for a in APPARTAMENTI_DEFAULT:
        if a.get(CONF_ID) == app_id:
            return a.get(CONF_NOME, app_id)
    return app_id


async def _resolve_entity_uids(
    hass: HomeAssistant, selezioni: dict[str, str]
) -> dict[str, str | None]:
    """Unique_id corrente per ogni entity_id selezionato (None se assente)."""
    er_registry = er.async_get(hass)
    uids: dict[str, str | None] = {}
    for chiave, entity_id in selezioni.items():
        entry = er_registry.async_get(entity_id)
        uids[chiave] = entry.unique_id if entry else None
    return uids


def _nome_base_climate(clima: str) -> str:
    """Estrae il nome-base da un climate (es. 'termostato_b_2_climatizzazione' -> 'termostato_b_2')."""
    if not clima:
        return ""
    core = clima.split(".", 1)[-1]
    if core.endswith("_climatizzazione"):
        return core[: -len("_climatizzazione")]
    return core


def _entity_exists(hass: HomeAssistant, entity_id: str) -> bool:
    """True se l'entity_id esiste nel registry."""
    return er.async_get(hass).async_get(entity_id) is not None


def _suggested_siblings(hass: HomeAssistant, clima: str) -> dict[str, str]:
    """Per ogni campo (temp_salvata/modalita/rinnovo), l'entity sorella suggerita (se esiste)."""
    base = _nome_base_climate(clima)
    if not base:
        return {}
    candidati = {
        CONF_TEMP_SALVATA: f"number.{base}_temperatura_salvata",
        CONF_MODALITA: f"switch.{base}_modalita_centralizzata",
        CONF_RINNOVO: f"button.{base}_rinnova_modalita_centralizzata",
    }
    return {
        chiave: eid
        for chiave, eid in candidati.items()
        if _entity_exists(hass, eid)
    }


class ClimaoroConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Wizard di configurazione Climaoro."""

    VERSION = 2

    def __init__(self) -> None:
        """Init."""
        self._gruppi: list[str] = []
        self._rooms: list[dict[str, Any]] = []
        self._edit_room_id: str | None = None
        self._edit_app_id: str | None = None
        self._draft: dict[str, Any] | None = None

    async def _commit_room(self, user_input: dict[str, Any]) -> None:
        """Persiste una stanza completata e rimanda al menu stanze."""
        uids = await _resolve_entity_uids(
            self.hass,
            {
                CONF_CLIMA: user_input[CONF_CLIMA],
                CONF_TEMP_SALVATA: user_input[CONF_TEMP_SALVATA],
                CONF_MODALITA: user_input[CONF_MODALITA],
                CONF_RINNOVO: user_input[CONF_RINNOVO],
            },
        )
        self._rooms.append(
            {
                "id": _slug(user_input[CONF_NOME]),
                CONF_NOME: user_input[CONF_NOME],
                CONF_APPARTAMENTO: user_input.get(
                    CONF_APPARTAMENTO, APPARTAMENTO_CASA
                ),
                CONF_GRUPPO: user_input[CONF_GRUPPO],
                CONF_CLIMA: user_input[CONF_CLIMA],
                CONF_TEMP_SALVATA: user_input[CONF_TEMP_SALVATA],
                CONF_MODALITA: user_input[CONF_MODALITA],
                CONF_RINNOVO: user_input[CONF_RINNOVO],
                CONF_CLIMA_UID: uids.get(CONF_CLIMA),
                CONF_TEMP_SALVATA_UID: uids.get(CONF_TEMP_SALVATA),
                CONF_MODALITA_UID: uids.get(CONF_MODALITA),
                CONF_RINNOVO_UID: uids.get(CONF_RINNOVO),
                CONF_PESO: user_input.get(CONF_PESO, DEFAULT_PESO),
                CONF_INCLUSIONE: user_input.get(CONF_INCLUSIONE, DEFAULT_INCLUSIONE),
            }
        )
        self._draft = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Step 1: scelta dei gruppi da usare."""
        errors: dict[str, str] = {}
        if user_input is not None:
            attivi = [g for g in GROUPS if user_input.get(f"gruppo_{g}")]
            if not attivi:
                errors["base"] = "nessun_gruppo"
            else:
                self._gruppi = attivi
                return await self.async_step_rooms()

        schema = {}
        for g in GROUPS:
            schema[vol.Optional(f"gruppo_{g}", default=True)] = bool
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    async def async_step_rooms(self, user_input: dict[str, Any] | None = None):
        """Menu stanze: aggiungi o termina."""
        if user_input is not None:
            if user_input["scelta"] == "aggiungi":
                return await self.async_step_add_room()
            if user_input["scelta"] == "gestisci":
                return await self.async_step_manage_room()
            return await self.async_step_global()

        desc = self._riepilogo_stanze()
        schema = {
            vol.Required("scelta"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "aggiungi", "label": "Aggiungi una stanza"},
                        {"value": "gestisci", "label": "Modifica/sposta una stanza"},
                        {"value": "fatto", "label": "Tutto a posto, continua"},
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        }
        return self.async_show_form(
            step_id="rooms",
            data_schema=vol.Schema(schema),
            description_placeholders={"riepilogo": desc},
        )

    def _riepilogo_stanze(self) -> str:
        if not self._rooms:
            return "Nessuna stanza aggiunta finora."
        righe = [
            f"- {r[CONF_NOME]} -> {_nome_app(r.get(CONF_APPARTAMENTO, APPARTAMENTO_CASA))} / "
            f"{GROUP_LABELS[r[CONF_GRUPPO]]} (peso {r.get(CONF_PESO, DEFAULT_PESO)}, "
            f"inclusa: {'si' if r.get(CONF_INCLUSIONE, True) else 'no'})"
            for r in self._rooms
        ]
        return "\n".join(righe)

    async def async_step_manage_room(self, user_input: dict[str, Any] | None = None):
        """Selezione stanza da modificare."""
        if user_input is not None:
            self._edit_room_id = user_input["room_id"]
            return await self.async_step_edit_room()

        schema = {
            vol.Required("room_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {
                            "value": r["id"],
                            "label": f"{r[CONF_NOME]} "
                            f"({_nome_app(r.get(CONF_APPARTAMENTO, APPARTAMENTO_CASA))} / "
                            f"{GROUP_LABELS[r[CONF_GRUPPO]]})",
                        }
                        for r in self._rooms
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }
        return self.async_show_form(step_id="manage_room", data_schema=vol.Schema(schema))

    async def async_step_edit_room(self, user_input: dict[str, Any] | None = None):
        """Modifica appartamento/gruppo/peso/inclusione di una stanza."""
        room_id = self._edit_room_id
        room = next((r for r in self._rooms if r["id"] == room_id), None)
        if room is None:
            return await self.async_step_rooms()

        if user_input is not None:
            room[CONF_APPARTAMENTO] = user_input[CONF_APPARTAMENTO]
            room[CONF_GRUPPO] = user_input[CONF_GRUPPO]
            room[CONF_PESO] = user_input[CONF_PESO]
            room[CONF_INCLUSIONE] = user_input[CONF_INCLUSIONE]
            self._edit_room_id = None
            return await self.async_step_rooms()

        schema = {
            vol.Required(
                CONF_APPARTAMENTO,
                default=room.get(CONF_APPARTAMENTO, APPARTAMENTO_CASA),
            ): _appartamento_selector({}, APPARTAMENTI_DEFAULT),
            vol.Required(CONF_GRUPPO, default=room.get(CONF_GRUPPO)): _gruppo_selector(),
            vol.Required(CONF_PESO, default=room.get(CONF_PESO, DEFAULT_PESO)): _numero(
                PESO_MIN, PESO_MAX, PESO_STEP
            ),
            vol.Required(
                CONF_INCLUSIONE, default=room.get(CONF_INCLUSIONE, DEFAULT_INCLUSIONE)
            ): selector.BooleanSelector(),
        }
        return self.async_show_form(
            step_id="edit_room",
            data_schema=vol.Schema(schema),
            description_placeholders={"nome": room[CONF_NOME]},
        )

    async def async_step_add_room(self, user_input: dict[str, Any] | None = None):
        """Passo 1/2: nome, appartamento, gruppo e termostato della stanza."""
        errors: dict[str, str] = {}
        if user_input is not None:
            nome = user_input[CONF_NOME].strip()
            if not nome:
                errors[CONF_NOME] = "nome_obbligatorio"
            elif any(r[CONF_NOME].lower() == nome.lower() for r in self._rooms):
                errors[CONF_NOME] = "nome_duplicato"
            else:
                self._draft = {
                    CONF_NOME: nome,
                    CONF_APPARTAMENTO: user_input.get(
                        CONF_APPARTAMENTO, APPARTAMENTO_CASA
                    ),
                    CONF_GRUPPO: user_input[CONF_GRUPPO],
                    CONF_CLIMA: user_input[CONF_CLIMA],
                }
                return await self.async_step_add_room_entities()

        schema = {
            vol.Required(CONF_NOME): str,
            vol.Required(
                CONF_APPARTAMENTO, default=APPARTAMENTO_CASA
            ): _appartamento_selector({}, APPARTAMENTI_DEFAULT),
            vol.Required(CONF_GRUPPO): _gruppo_selector(),
            vol.Required(CONF_CLIMA): _entity_selector(["climate"]),
        }
        return self.async_show_form(
            step_id="add_room",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={"riepilogo": self._riepilogo_stanze()},
        )

    async def async_step_add_room_entities(
        self, user_input: dict[str, Any] | None = None
    ):
        """Passo 2/2: entita' affini al termostato (suggerite), peso e inclusione."""
        suggeriti = _suggested_siblings(self.hass, self._draft[CONF_CLIMA])
        errors: dict[str, str] = {}
        if user_input is not None:
            completo = dict(self._draft or {})
            completo.update(user_input)
            await self._commit_room(completo)
            return await self.async_step_rooms()

        schema = {
            vol.Required(
                CONF_TEMP_SALVATA, default=suggeriti.get(CONF_TEMP_SALVATA, "")
            ): _entity_selector(["number"]),
            vol.Required(
                CONF_MODALITA, default=suggeriti.get(CONF_MODALITA, "")
            ): _entity_selector(["switch"]),
            vol.Required(
                CONF_RINNOVO, default=suggeriti.get(CONF_RINNOVO, "")
            ): _entity_selector(["button"]),
            vol.Required(CONF_PESO, default=DEFAULT_PESO): _numero(PESO_MIN, PESO_MAX, PESO_STEP),
            vol.Required(CONF_INCLUSIONE, default=DEFAULT_INCLUSIONE): selector.BooleanSelector(),
        }
        return self.async_show_form(
            step_id="add_room_entities",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={"nome": self._draft[CONF_NOME]},
        )

    async def async_step_global(self, user_input: dict[str, Any] | None = None):
        """Attivo + soglia pesi applicati a TUTTI gli appartamenti."""
        if user_input is not None:
            if not self._rooms:
                return self.async_abort(reason="nessuna_stanza")
            data = {
                "data": {
                    CONF_APPARTAMENTI: default_appartamenti(self._gruppi),
                    CONF_ROOMS: self._rooms,
                }
            }
            for ap in data["data"][CONF_APPARTAMENTI]:
                ap[CONF_ATTIVO] = user_input.get(CONF_ATTIVO, DEFAULT_ATTIVO)
                ap[CONF_SOGLIA_PESI] = user_input.get(
                    CONF_SOGLIA_PESI, DEFAULT_SOGLIA_PESI
                )
            return self.async_create_entry(title="ClimaORO", data=data)

        schema = {
            vol.Required(CONF_ATTIVO, default=DEFAULT_ATTIVO): selector.BooleanSelector(),
            vol.Required(CONF_SOGLIA_PESI, default=DEFAULT_SOGLIA_PESI): _numero(
                SOGLIA_MIN, SOGLIA_MAX, SOGLIA_STEP
            ),
        }
        return self.async_show_form(
            step_id="global",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "n": len(APPARTAMENTI_DEFAULT),
                "nomi": ", ".join(a.get(CONF_NOME) for a in APPARTAMENTI_DEFAULT),
            },
        )


class ClimaoroOptionsFlow(config_entries.OptionsFlow):
    """Opzioni: stanze, delta dei gruppi e parametri globali per appartamento."""

    VERSION = 2

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        """Init."""
        self._entry = entry
        self._data = migrate_options(copy.deepcopy(dict(entry.options)))
        self._edit_room_id: str | None = None
        self._app_id: str | None = None
        self._target: str | None = None
        self._draft: dict[str, Any] | None = None

    async def _commit_room_options(self, user_input: dict[str, Any]) -> None:
        """Persiste una stanza completata nelle options e torna al menu stanze."""
        uids = await _resolve_entity_uids(
            self.hass,
            {
                CONF_CLIMA: user_input[CONF_CLIMA],
                CONF_TEMP_SALVATA: user_input[CONF_TEMP_SALVATA],
                CONF_MODALITA: user_input[CONF_MODALITA],
                CONF_RINNOVO: user_input[CONF_RINNOVO],
            },
        )
        rooms = list(self._data.get(CONF_ROOMS, [])) + [
            {
                "id": _slug(user_input[CONF_NOME]),
                CONF_NOME: user_input[CONF_NOME],
                CONF_APPARTAMENTO: user_input.get(
                    CONF_APPARTAMENTO, APPARTAMENTO_CASA
                ),
                CONF_GRUPPO: user_input[CONF_GRUPPO],
                CONF_CLIMA: user_input[CONF_CLIMA],
                CONF_TEMP_SALVATA: user_input[CONF_TEMP_SALVATA],
                CONF_MODALITA: user_input[CONF_MODALITA],
                CONF_RINNOVO: user_input[CONF_RINNOVO],
                CONF_CLIMA_UID: uids.get(CONF_CLIMA),
                CONF_TEMP_SALVATA_UID: uids.get(CONF_TEMP_SALVATA),
                CONF_MODALITA_UID: uids.get(CONF_MODALITA),
                CONF_RINNOVO_UID: uids.get(CONF_RINNOVO),
                CONF_PESO: user_input.get(CONF_PESO, DEFAULT_PESO),
                CONF_INCLUSIONE: user_input.get(CONF_INCLUSIONE, DEFAULT_INCLUSIONE),
            }
        ]
        self._data[CONF_ROOMS] = rooms
        self._draft = None

    def _ap(self) -> dict[str, Any] | None:
        for ap in self._data.get(CONF_APPARTAMENTI, []):
            if ap.get(CONF_ID) == self._app_id:
                return ap
        return None

    def _save_ap(self, ap: dict[str, Any]) -> None:
        appartamenti = self._data.get(CONF_APPARTAMENTI, [])
        for i, x in enumerate(appartamenti):
            if x.get(CONF_ID) == ap.get(CONF_ID):
                appartamenti[i] = ap
        self._data[CONF_APPARTAMENTI] = appartamenti

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Menu principale opzioni."""
        if user_input is not None:
            scelta = user_input["scelta"]
            if scelta == "stanze":
                return await self.async_step_rooms()
            if scelta == "gruppi":
                self._target = "gruppi"
                return await self.async_step_select_apartment()
            if scelta == "globali":
                self._target = "globali"
                return await self.async_step_select_apartment()
            return self.async_create_entry(title="", data=self._data)

        schema = {
            vol.Required("scelta"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "stanze", "label": "Gestisci le stanze (aggiungi, sposta, peso, inclusione)"},
                        {"value": "gruppi", "label": "Delta dei gruppi (comfort / eco)"},
                        {"value": "globali", "label": "Parametri globali per appartamento (attivo, soglia pesi)"},
                        {"value": "fine", "label": "Salva e chiudi"},
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        }
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))

    async def async_step_select_apartment(self, user_input: dict[str, Any] | None = None):
        """Scegli l'appartamento (per gruppi o parametri globali)."""
        if user_input is not None:
            self._app_id = user_input[CONF_APPARTAMENTO]
            if self._target == "gruppi":
                return await self.async_step_select_group()
            return await self.async_step_edit_global()

        schema = {
            vol.Required(CONF_APPARTAMENTO): _appartamento_selector(self._data)
        }
        return self.async_show_form(
            step_id="select_apartment", data_schema=vol.Schema(schema)
        )

    async def async_step_rooms(self, user_input: dict[str, Any] | None = None):
        """Menu stanze nelle opzioni."""
        if user_input is not None:
            if user_input["scelta"] == "aggiungi":
                return await self.async_step_add_room()
            if user_input["scelta"] == "gestisci":
                return await self.async_step_manage_room()
            return await self.async_step_init()

        schema = {
            vol.Required("scelta"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "aggiungi", "label": "Aggiungi una stanza"},
                        {"value": "gestisci", "label": "Sposta/modifica una stanza"},
                        {"value": "indietro", "label": "Indietro"},
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        }
        return self.async_show_form(step_id="rooms", data_schema=vol.Schema(schema))

    async def async_step_add_room(self, user_input: dict[str, Any] | None = None):
        """Passo 1/2: nome, appartamento, gruppo e termostato della stanza."""
        errors: dict[str, str] = {}
        if user_input is not None:
            nome = user_input[CONF_NOME].strip()
            rooms = self._data.get(CONF_ROOMS, [])
            if not nome:
                errors[CONF_NOME] = "nome_obbligatorio"
            elif any(r[CONF_NOME].lower() == nome.lower() for r in rooms):
                errors[CONF_NOME] = "nome_duplicato"
            else:
                self._draft = {
                    CONF_NOME: nome,
                    CONF_APPARTAMENTO: user_input.get(
                        CONF_APPARTAMENTO, APPARTAMENTO_CASA
                    ),
                    CONF_GRUPPO: user_input[CONF_GRUPPO],
                    CONF_CLIMA: user_input[CONF_CLIMA],
                }
                return await self.async_step_add_room_entities()

        schema = {
            vol.Required(CONF_NOME): str,
            vol.Required(
                CONF_APPARTAMENTO, default=APPARTAMENTO_CASA
            ): _appartamento_selector(self._data),
            vol.Required(CONF_GRUPPO): _gruppo_selector(),
            vol.Required(CONF_CLIMA): _entity_selector(["climate"]),
        }
        return self.async_show_form(step_id="add_room", data_schema=vol.Schema(schema), errors=errors)

    async def async_step_add_room_entities(
        self, user_input: dict[str, Any] | None = None
    ):
        """Passo 2/2: entita' affini al termostato (suggerite), peso e inclusione."""
        suggeriti = _suggested_siblings(self.hass, self._draft[CONF_CLIMA])
        errors: dict[str, str] = {}
        if user_input is not None:
            completo = dict(self._draft or {})
            completo.update(user_input)
            await self._commit_room_options(completo)
            return await self.async_step_rooms()

        schema = {
            vol.Required(
                CONF_TEMP_SALVATA, default=suggeriti.get(CONF_TEMP_SALVATA, "")
            ): _entity_selector(["number"]),
            vol.Required(
                CONF_MODALITA, default=suggeriti.get(CONF_MODALITA, "")
            ): _entity_selector(["switch"]),
            vol.Required(
                CONF_RINNOVO, default=suggeriti.get(CONF_RINNOVO, "")
            ): _entity_selector(["button"]),
            vol.Required(CONF_PESO, default=DEFAULT_PESO): _numero(PESO_MIN, PESO_MAX, PESO_STEP),
            vol.Required(CONF_INCLUSIONE, default=DEFAULT_INCLUSIONE): selector.BooleanSelector(),
        }
        return self.async_show_form(
            step_id="add_room_entities",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={"nome": self._draft[CONF_NOME]},
        )

    async def async_step_manage_room(self, user_input: dict[str, Any] | None = None):
        """Selezione stanza da modificare/spostare."""
        rooms = self._data.get(CONF_ROOMS, [])
        if user_input is not None:
            self._edit_room_id = user_input["room_id"]
            return await self.async_step_edit_room()

        schema = {
            vol.Required("room_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {
                            "value": r["id"],
                            "label": f"{r[CONF_NOME]} "
                            f"({_nome_app(r.get(CONF_APPARTAMENTO, APPARTAMENTO_CASA))} / "
                            f"{GROUP_LABELS[r[CONF_GRUPPO]]})",
                        }
                        for r in rooms
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }
        return self.async_show_form(step_id="manage_room", data_schema=vol.Schema(schema))

    async def async_step_edit_room(self, user_input: dict[str, Any] | None = None):
        """Sposta stanza tra appartamenti/gruppi / modifica peso e inclusione."""
        rooms = self._data.get(CONF_ROOMS, [])
        room = next((r for r in rooms if r["id"] == self._edit_room_id), None)
        if room is None:
            return await self.async_step_rooms()

        if user_input is not None:
            room[CONF_APPARTAMENTO] = user_input[CONF_APPARTAMENTO]
            room[CONF_GRUPPO] = user_input[CONF_GRUPPO]
            room[CONF_PESO] = user_input[CONF_PESO]
            room[CONF_INCLUSIONE] = user_input[CONF_INCLUSIONE]
            self._data[CONF_ROOMS] = rooms
            self._edit_room_id = None
            return await self.async_step_rooms()

        schema = {
            vol.Required(
                CONF_APPARTAMENTO,
                default=room.get(CONF_APPARTAMENTO, APPARTAMENTO_CASA),
            ): _appartamento_selector(self._data),
            vol.Required(CONF_GRUPPO, default=room.get(CONF_GRUPPO)): _gruppo_selector(),
            vol.Required(CONF_PESO, default=room.get(CONF_PESO, DEFAULT_PESO)): _numero(
                PESO_MIN, PESO_MAX, PESO_STEP
            ),
            vol.Required(CONF_INCLUSIONE, default=room.get(CONF_INCLUSIONE, DEFAULT_INCLUSIONE)): selector.BooleanSelector(),
        }
        return self.async_show_form(
            step_id="edit_room",
            data_schema=vol.Schema(schema),
            description_placeholders={"nome": room[CONF_NOME]},
        )

    async def async_step_select_group(self, user_input: dict[str, Any] | None = None):
        """Selezione gruppo da modificare (nell'appartamento scelto)."""
        ap = self._ap()
        if ap is None:
            return self.async_abort(reason="nessun_appartamento")
        groups = ap.get(CONF_GROUPS, {})
        if user_input is not None:
            gruppo = user_input["gruppo"]
            return await self.async_step_edit_group(gruppo=gruppo)

        options = [
            {"value": g, "label": GROUP_LABELS[g]}
            for g in groups
        ]
        if not options:
            return self.async_abort(reason="nessun_gruppo")
        schema = {
            vol.Required("gruppo"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.DROPDOWN)
            )
        }
        return self.async_show_form(step_id="select_group", data_schema=vol.Schema(schema))

    async def async_step_edit_group(
        self, user_input: dict[str, Any] | None = None, gruppo: str | None = None
    ):
        """Modifica delta di un gruppo di un appartamento."""
        ap = self._ap()
        if ap is None:
            return self.async_abort(reason="nessun_appartamento")
        groups = ap.get(CONF_GROUPS, {})
        if user_input is not None:
            g = dict(groups.get(user_input["_gruppo"], {}))
            g[CONF_DELTA_ACCENSIONE_COMFORT] = user_input[CONF_DELTA_ACCENSIONE_COMFORT]
            g[CONF_DELTA_ACCENSIONE_ECO] = user_input[CONF_DELTA_ACCENSIONE_ECO]
            g[CONF_DELTA_SPEGNIMENTO_COMFORT] = user_input[CONF_DELTA_SPEGNIMENTO_COMFORT]
            g[CONF_DELTA_SPEGNIMENTO_ECO] = user_input[CONF_DELTA_SPEGNIMENTO_ECO]
            groups[user_input["_gruppo"]] = g
            ap[CONF_GROUPS] = groups
            self._save_ap(ap)
            return await self.async_step_init()

        g = groups.get(gruppo, {})
        schema = {
            vol.Required("_gruppo", default=gruppo): str,
            vol.Required(
                CONF_DELTA_ACCENSIONE_COMFORT,
                default=g.get(CONF_DELTA_ACCENSIONE_COMFORT, DEFAULT_DELTA_ACCENSIONE_COMFORT),
            ): _numero(DELTA_ACCENSIONE_COMFORT_MIN, DELTA_ACCENSIONE_COMFORT_MAX, DELTA_STEP),
            vol.Required(
                CONF_DELTA_ACCENSIONE_ECO,
                default=g.get(CONF_DELTA_ACCENSIONE_ECO, DEFAULT_DELTA_ACCENSIONE_ECO),
            ): _numero(DELTA_ACCENSIONE_ECO_MIN, DELTA_ACCENSIONE_ECO_MAX, DELTA_STEP),
            vol.Required(
                CONF_DELTA_SPEGNIMENTO_COMFORT,
                default=g.get(CONF_DELTA_SPEGNIMENTO_COMFORT, DEFAULT_DELTA_SPEGNIMENTO_COMFORT),
            ): _numero(DELTA_SPEGNIMENTO_COMFORT_MIN, DELTA_SPEGNIMENTO_COMFORT_MAX, DELTA_STEP),
            vol.Required(
                CONF_DELTA_SPEGNIMENTO_ECO,
                default=g.get(CONF_DELTA_SPEGNIMENTO_ECO, DEFAULT_DELTA_SPEGNIMENTO_ECO),
            ): _numero(DELTA_SPEGNIMENTO_ECO_MIN, DELTA_SPEGNIMENTO_ECO_MAX, DELTA_STEP),
        }
        return self.async_show_form(
            step_id="edit_group",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "gruppo": GROUP_LABELS.get(gruppo, gruppo),
                "nome": ap.get(CONF_NOME, self._app_id),
            },
        )

    async def async_step_edit_global(self, user_input: dict[str, Any] | None = None):
        """Modifica parametri globali di un appartamento."""
        ap = self._ap()
        if ap is None:
            return self.async_abort(reason="nessun_appartamento")

        if user_input is not None:
            ap[CONF_ATTIVO] = user_input[CONF_ATTIVO]
            ap[CONF_SOGLIA_PESI] = user_input[CONF_SOGLIA_PESI]
            self._save_ap(ap)
            return await self.async_step_init()

        schema = {
            vol.Required(CONF_ATTIVO, default=ap.get(CONF_ATTIVO, DEFAULT_ATTIVO)): selector.BooleanSelector(),
            vol.Required(CONF_SOGLIA_PESI, default=ap.get(CONF_SOGLIA_PESI, DEFAULT_SOGLIA_PESI)): _numero(
                SOGLIA_MIN, SOGLIA_MAX, SOGLIA_STEP
            ),
        }
        return self.async_show_form(
            step_id="edit_global",
            data_schema=vol.Schema(schema),
            description_placeholders={"nome": ap.get(CONF_NOME, self._app_id)},
        )


@callback
def async_get_options_flow(entry: config_entries.ConfigEntry):
    """Options flow."""
    return ClimaoroOptionsFlow(entry)
