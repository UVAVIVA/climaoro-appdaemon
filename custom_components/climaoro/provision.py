"""Provisioning automatico dell'integrazione Climaoro.

Dopo il wizard (o tramite il servizio ``climaoro.provisiona``) l'integrazione:
  1. genera un long-lived token per AppDaemon;
  2. scrive ``climaoro.py`` + ``apps.yaml`` dentro l'addon AppDaemon
     (via ``init_commands`` nelle opzioni dell'addon: girano nel
     container addon dove ``/config`` e' il mount host reale);
  3. riavvia l'addon AppDaemon se i file sono cambiati;
  4. crea/aggiorna la dashboard Lovelace "Climaoro" (con il calendario
     7x24 editabile) usando la config runtime (rename-proof);
  5. registra la risorsa frontend della card ``climaoro-calendario``.
"""

from __future__ import annotations

import base64
import inspect
import json
import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import build_runtime_config
from .const import (
    CONF_ATTIVO,
    CONF_CLIMA,
    CONF_DELTA_COMFORT,
    CONF_DELTA_ECO,
    CONF_INCLUSIONE,
    CONF_MODALITA,
    CONF_NOME,
    CONF_PESO,
    CONF_RINNOVO,
    CONF_SOGLIA_PESI,
    CONF_TEMP_SALVATA,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_APPD_ADDON = "a0d7b954_appdaemon"
DASHBOARD_URL_PATH = "climaoro-panel"
DASHBOARD_TITLE = "Climaoro"
CARD_URL = "/local/climaoro/climaoro-calendario.js"
APPS_DIR = "apps"
APPS_YAML = "apps.yaml"
APP_FILE = "climaoro.py"
HA_URL_ADDON = "http://supervisor/core"
TOKEN_NAME = "Climaoro AppDaemon"


async def async_generate_token(hass: HomeAssistant) -> str | None:
    """Long-lived token per AppDaemon (utente owner/admin)."""
    users = await hass.auth.async_get_users()
    user = None
    for u in users:
        if getattr(u, "system_generated", False) or getattr(u, "is_system", False):
            continue
        if getattr(u, "is_owner", False) or getattr(u, "is_admin", False):
            user = u
            break
    if user is None:
        _LOGGER.error("Nessun utente owner/admin non-di-sistema: token non creato")
        return None
    try:
        existing = next(
            (
                rt
                for rt in getattr(user, "refresh_tokens", {}).values()
                if getattr(rt, "client_name", None) == TOKEN_NAME
            ),
            None,
        )
        if existing is not None:
            return hass.auth.async_create_access_token(existing)
        refresh_token = await hass.auth.async_create_refresh_token(
            user,
            client_name=TOKEN_NAME,
            token_type="long_lived_access_token",
            access_token_expiration=timedelta(days=3650),
        )
        return hass.auth.async_create_access_token(refresh_token)
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Creazione token fallita: %s", err)
        return None


async def _get_addon_manager(hass: HomeAssistant):
    """Istanza AddonManager per l'addon AppDaemon."""
    from homeassistant.components.hassio.addon_manager import AddonManager
    from homeassistant.components.hassio import DOMAIN as HASSIO_DOMAIN

    hassio = hass.data.get(HASSIO_DOMAIN)
    if hassio is None:
        _LOGGER.error("Componente hassio non attivo")
        return None
    try:
        return AddonManager(hass, _LOGGER, "AppDaemon", DEFAULT_APPD_ADDON)
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("AddonManager init fallito: %s", err)
        return None


async def async_get_addon_slug(hass: HomeAssistant) -> str | None:
    """Slug dell'addon AppDaemon installato."""
    mgr = await _get_addon_manager(hass)
    if mgr is None:
        return None
    try:
        info = await mgr.async_get_addon_info()
        state = getattr(info, "state", None)
        if state in (None, "unknown"):
            _LOGGER.warning("Addon %s non installato (state=%s)", DEFAULT_APPD_ADDON, state)
            return None
        _LOGGER.debug(
            "Addon %s ok: state=%s version=%s",
            DEFAULT_APPD_ADDON,
            state,
            getattr(info, "version", None),
        )
        return DEFAULT_APPD_ADDON
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Addon %s non disponibile: %s", DEFAULT_APPD_ADDON, err)
    return None


async def async_write_appdaemon_files(
    hass: HomeAssistant, slug: str, token: str
) -> bool:
    """Prepara app+apps.yaml per l'addon AppDaemon.

    Su HAOS il mount ``/addon_configs`` dentro il container core e'
    copy-on-write: le scritture dirette non raggiungono mai l'addon.
    La via affidabile e' impostare ``init_commands`` nelle opzioni
    dell'addon: girano dentro il container addon dove ``/config`` e'
    il mount host reale, quindi i file finiscono nella vera
    ``/addon_configs/<slug>/apps``. Ritorna True se serve un riavvio.
    """
    src_app = Path(__file__).parent / "appdaemon_app" / APP_FILE
    if not src_app.exists():
        _LOGGER.error("App sorgente mancante: %s", src_app)
        return False

    app_source = src_app.read_text(encoding="utf-8")
    apps_yaml = (
        f"# Generato automaticamente da Climaoro ({TOKEN_NAME}).\n"
        f"climaoro:\n"
        f"  module: {APP_FILE[:-3]}\n"
        f"  class: Climaoro\n"
        f"  ha_url: {HA_URL_ADDON}\n"
        f"  token: {token}\n"
    )
    app_b64 = base64.b64encode(app_source.encode()).decode()
    yaml_b64 = base64.b64encode(apps_yaml.encode()).decode()

    command = (
        "echo climaoro-provision-ok && "
        f"mkdir -p /config/apps && "
        f"echo {app_b64} | base64 -d > /config/apps/{APP_FILE} && "
        f"echo {yaml_b64} | base64 -d > /config/apps/{APPS_YAML}"
    )

    mgr = await _get_addon_manager(hass)
    if mgr is None:
        return _write_appdaemon_files_direct(slug, app_source, apps_yaml)

    try:
        info = await mgr.async_get_addon_info()
        options = dict(getattr(info, "options", {}) or {})
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Lettura opzioni addon fallita: %s", err)
        return _write_appdaemon_files_direct(slug, app_source, apps_yaml)

    old_commands = list(options.get("init_commands") or [])
    keep = [c for c in old_commands if "climaoro-provision" not in c]
    new_commands = keep + [command]
    if old_commands == new_commands:
        _LOGGER.debug("Config AppDaemon gia' aggiornata, niente da fare")
        return False

    options["init_commands"] = new_commands
    try:
        await mgr.async_set_addon_options(options)
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Impostazione opzioni addon fallita: %s", err)
        return _write_appdaemon_files_direct(slug, app_source, apps_yaml)
    _LOGGER.info("Opzioni AppDaemon aggiornate (init_commands climaoro)")
    return True


def _write_appdaemon_files_direct(slug: str, app_source: str, apps_yaml: str) -> bool:
    """Fallback: scrittura diretta su /addon_configs (solo se e' un mount reale)."""
    base = Path(f"/addon_configs/{slug}/{APPS_DIR}")
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        _LOGGER.error("Mount /addon_configs non scrivibile: %s", err)
        return False

    changed = False
    for name, content in ((APP_FILE, app_source), (APPS_YAML, apps_yaml)):
        target = base / name
        try:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                target.write_text(content, encoding="utf-8")
                changed = True
        except OSError as err:
            _LOGGER.error("Scrittura %s fallita: %s", name, err)
            return False
    return changed


async def async_restart_addon(hass: HomeAssistant, slug: str) -> bool:
    """Riavvia l'addon AppDaemon (o lo avvia se fermo)."""
    mgr = await _get_addon_manager(hass)
    if mgr is None:
        return False
    try:
        from homeassistant.components.hassio.addon_manager import AddonState

        info = await mgr.async_get_addon_info()
        if getattr(info, "state", None) == AddonState.NOT_RUNNING:
            await mgr.async_start_addon()
        else:
            await mgr.async_restart_addon()
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Riavvio addon AppDaemon fallito: %s", err)
        return False


def build_dashboard_config(cfg: dict) -> dict:
    """Dashboard Lovelace dalla config runtime (stessa logica dello script tool)."""
    gen = cfg.get("global", {}).get("entities", {})
    cards: list[dict] = [
        {
            "type": "entities",
            "title": "Climaoro - Globale",
            "entities": [
                {"entity": gen.get("attivo"), "name": "Sistema attivo"},
                {"entity": gen.get("soglia_pesi"), "name": "Soglia pesi"},
            ],
        }
    ]

    for gruppo in cfg.get("gruppi", []):
        gent = gruppo.get("entities", {})
        label = gruppo.get("label", gruppo.get("id"))
        cards.append(
            {
                "type": "entities",
                "title": f"Gruppo {label}",
                "entities": [
                    {"entity": gent.get("delta_comfort"), "name": "Delta comfort"},
                    {"entity": gent.get("delta_eco"), "name": "Delta eco"},
                    {"entity": gent.get("calendario"), "name": "Calendario"},
                ],
            }
        )
        cards.append(
            {
                "type": "custom:climaoro-calendario",
                "gruppo": gruppo.get("id"),
                "entity": gent.get("calendario"),
            }
        )
        for stanza in gruppo.get("stanze", []):
            ent = stanza.get("entities", {})
            stanza_entities = [
                {"entity": ent.get("clima"), "name": "Climatizzazione"},
                {"entity": ent.get("temp_salvata"), "name": "Temperatura salvata"},
                {"entity": ent.get("peso"), "name": "Peso"},
                {"entity": ent.get("inclusione"), "name": "Inclusione"},
                {"entity": ent.get("modalita"), "name": "Modalita centralizzata"},
                {"entity": ent.get("rinnovo"), "name": "Rinnova modalita"},
            ]
            cards.append(
                {
                    "type": "entities",
                    "title": str(stanza.get("nome")),
                    "entities": [e for e in stanza_entities if e.get("entity")],
                }
            )

    return {"views": [{"title": DASHBOARD_TITLE, "cards": cards}]}


async def _ws_run(hass: HomeAssistant, func) -> str | None:
    """Esegue comandi websocket su se stesso (fallback)."""
    token = await async_generate_token(hass)
    if not token:
        return None
    import websockets

    base = (
        hass.config.internal_url
        or hass.config.external_url
        or "http://supervisor/core"
    )
    ws_url = str(base).rstrip("/").replace("http", "ws") + "/api/websocket"
    try:
        async with websockets.connect(ws_url) as ws:
            await ws.recv()
            await ws.send(json.dumps({"type": "auth", "access_token": token}))
            msg = json.loads(await ws.recv())
            if msg.get("type") != "auth_ok":
                _LOGGER.error("Auth websocket fallita: %s", msg)
                return None
            return await func(ws)
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Websocket self fallita: %s", err)
        return None


async def async_ensure_dashboard(hass: HomeAssistant, config: dict) -> str | None:
    """Crea/aggiorna la dashboard Climaoro."""
    try:
        from homeassistant.components.lovelace import LOVELACE_DATA
        from homeassistant.components.lovelace.dashboard import (
            DASHBOARDS_STORAGE_KEY,
            DASHBOARDS_STORAGE_VERSION,
            LovelaceStorage,
        )
        from homeassistant.helpers.storage import Store

        manager = hass.data.get(LOVELACE_DATA)
        dashboards = getattr(manager, "dashboards", None) if manager else None
        if isinstance(dashboards, dict):
            dash = dashboards.get(DASHBOARD_URL_PATH)
            if dash is None:
                dash = LovelaceStorage(hass, DASHBOARD_URL_PATH)
                dashboards[DASHBOARD_URL_PATH] = dash
                store = Store(
                    hass, DASHBOARDS_STORAGE_VERSION, DASHBOARDS_STORAGE_KEY
                )
                reg = await store.async_load() or {"items": []}
                if not any(
                    i.get("url_path") == DASHBOARD_URL_PATH
                    for i in reg.get("items", [])
                ):
                    reg.setdefault("items", []).append(
                        {
                            "id": "climaoro_panel",
                            "url_path": DASHBOARD_URL_PATH,
                            "mode": "storage",
                            "title": DASHBOARD_TITLE,
                            "require_admin": False,
                            "show_in_sidebar": True,
                        }
                    )
                    await store.async_save(reg)
            await dash.async_save(config)
            return "ok (lovelace internals)"
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Dashboard via internals fallita (%s), provo websocket", err)

    async def _save(ws):
        await ws.send(
            json.dumps(
                {
                    "id": 1,
                    "type": "lovelace/dashboards/create",
                    "url_path": DASHBOARD_URL_PATH,
                    "mode": "storage",
                    "title": DASHBOARD_TITLE,
                }
            )
        )
        msg = json.loads(await ws.recv())
        if msg.get("type") == "result" and not msg.get("success"):
            err = msg.get("error", {}) or {}
            already = err.get("code") in ("already_exists", "url_already_exists") or (
                "already in use" in (err.get("message") or "")
            )
            if not already:
                _LOGGER.error("Create dashboard: %s", msg)
                return None
        await ws.send(
            json.dumps(
                {
                    "id": 2,
                    "type": "lovelace/config/save",
                    "url_path": DASHBOARD_URL_PATH,
                    "config": config,
                }
            )
        )
        msg = json.loads(await ws.recv())
        if not (msg.get("type") == "result" and msg.get("success")):
            _LOGGER.error("Save dashboard: %s", msg)
            return None
        return "ok (websocket)"

    return await _ws_run(hass, _save)


async def async_ensure_resource(hass: HomeAssistant) -> str | None:
    """Registra la risorsa JS della card calendario (dedup di tutte le URL climaoro)."""
    try:
        from homeassistant.components.lovelace import LOVELACE_DATA

        manager = hass.data.get(LOVELACE_DATA)
        resources = getattr(manager, "resources", None)
        if resources is not None:
            items = resources.async_items()

            def _url(i) -> str | None:
                return i.get("url") if isinstance(i, dict) else getattr(i, "url", None)

            def _id(i) -> str | None:
                return i.get("id") if isinstance(i, dict) else getattr(i, "id", None)

            has_target = any(_url(i) == CARD_URL for i in items)
            created = False
            if not has_target:
                await resources.async_create_item(
                    {"res_type": "module", "url": CARD_URL}
                )
                created = True

            kept_one = False
            removed = 0
            for i in list(resources.async_items()):
                u = _url(i)
                if not (isinstance(u, str) and "climaoro" in u):
                    continue
                if u == CARD_URL and not kept_one:
                    kept_one = True
                    continue
                await resources.async_delete_item(_id(i))
                removed += 1

            if created:
                return "ok (risorsa creata)"
            return f"ok (risorsa presente, {removed} duplicati rimossi)"
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Risorsa via internals fallita (%s), provo websocket", err)

    async def _resource(ws):
        await ws.send(json.dumps({"id": 1, "type": "lovelace/resources"}))
        msg = json.loads(await ws.recv())
        if not (msg.get("type") == "result" and msg.get("success")):
            _LOGGER.error("Lista risorse: %s", msg)
            return None
        items = msg.get("result", [])
        if any(i.get("url") == CARD_URL for i in items):
            return "ok (risorsa gia' presente)"
        await ws.send(
            json.dumps(
                {
                    "id": 2,
                    "type": "lovelace/resources/create",
                    "res_type": "module",
                    "url": CARD_URL,
                }
            )
        )
        msg = json.loads(await ws.recv())
        if not (msg.get("type") == "result" and msg.get("success")):
            _LOGGER.error("Create risorsa: %s", msg)
            return None
        return "ok (risorsa creata)"

    return await _ws_run(hass, _resource)


async def async_provision(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    """Esegue tutto il provisioning. Ritorna le righe di report."""
    results: list[str] = []

    token = await async_generate_token(hass)
    if not token:
        results.append("token: fallito (salto AppDaemon)")
    else:
        slug = await async_get_addon_slug(hass)
        if slug is None:
            results.append("AppDaemon: addon non trovato")
        else:
            try:
                changed = await async_write_appdaemon_files(hass, slug, token)
                results.append(f"AppDaemon: file scritti ({slug})")
                if changed:
                    ok = await async_restart_addon(hass, slug)
                    results.append(f"AppDaemon: riavvio {'ok' if ok else 'fallito'}")
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("AppDaemon provisioning fallito: %s", err)
                results.append("AppDaemon: errore (vedi log)")

    try:
        cfg = await build_runtime_config(hass)
        config = build_dashboard_config(cfg)
        dash = await async_ensure_dashboard(hass, config)
        results.append(f"dashboard: {dash}")
        res = await async_ensure_resource(hass)
        results.append(f"risorsa card: {res}")
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Dashboard provisioning fallito: %s", err)
        results.append("dashboard: errore (vedi log)")

    return results
