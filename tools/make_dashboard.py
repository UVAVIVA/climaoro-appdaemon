"""Crea (o aggiorna) la dashboard Lovelace "Climaoro" su HA.

La dashboard viene costruita dinamicamente dalla config runtime
(/api/climaoro/config): nessun entity_id hardcoded. Se l'utente rinomina
un'entita', basta rieseguire questo script.

Uso:
    python make_dashboard.py --url http://192.168.1.132:80 \
        --token <long-lived-token> [--url-path climaoro-panel] [--title Climaoro]
"""

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request

import websockets


def fetch_runtime_config(ha_url: str, token: str) -> dict:
    req = urllib.request.Request(
        f"{ha_url}/api/climaoro/config",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def build_dashboard(cfg: dict) -> dict:
    """Dashboard Lovelace: una vista per appartamento (globale + gruppi)."""
    views = []
    for ap in cfg.get("appartamenti", []):
        nome = ap.get("nome", ap.get("id"))
        ap_id = ap.get("id")
        gen = ap.get("entities", {})

        cards = [
            {
                "type": "entities",
                "title": f"Globale {nome}",
                "entities": [
                    {"entity": gen.get("attivo"), "name": "Sistema attivo"},
                    {"entity": gen.get("soglia_pesi"), "name": "Soglia pesi"},
                ],
            }
        ]

        for gruppo in ap.get("gruppi", []):
            gent = gruppo.get("entities", {})
            label = gruppo.get("label", gruppo.get("id"))
            cards.append(
                {
                    "type": "entities",
                    "title": f"{nome} · Gruppo {label}",
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
                    "title": f"{nome} · Calendario {label}",
                    "appartamento": ap_id,
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
                        "title": f"{nome} · {label} · {stanza.get('nome')}",
                        "entities": [e for e in stanza_entities if e.get("entity")],
                    }
                )

        views.append(
            {
                "title": nome,
                "path": ap_id,
                "cards": cards,
            }
        )

    return {"views": views}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="URL base HA (es. http://192.168.1.132:80)")
    parser.add_argument("--token", required=True, help="Token long-lived HA")
    parser.add_argument("--url-path", default="climaoro-panel", help="url_path dashboard (deve contenere un trattino)")
    parser.add_argument("--title", default="Climaoro", help="Titolo dashboard")
    args = parser.parse_args()

    ha_url = args.url.rstrip("/")
    ws_url = ha_url.replace("http", "ws") + "/api/websocket"
    cfg = fetch_runtime_config(ha_url, args.token)
    print(f"config runtime: appartamenti={len(cfg.get('appartamenti', []))} entita={len(cfg.get('entities', {}))}")
    dashboard_config = build_dashboard(cfg)

    async with websockets.connect(ws_url) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": args.token}))
        msg = json.loads(await ws.recv())
        if msg.get("type") != "auth_ok":
            print("Auth fallita:", msg)
            sys.exit(1)

        await ws.send(json.dumps({
            "id": 1,
            "type": "lovelace/dashboards/create",
            "url_path": args.url_path,
            "mode": "storage",
            "title": args.title,
        }))
        msg = json.loads(await ws.recv())
        if msg.get("type") == "result" and not msg.get("success"):
            err = msg.get("error", {}) or {}
            already = (
                err.get("code") in ("already_exists", "url_already_exists")
                or "already in use" in (err.get("message") or "")
            )
            if not already:
                print("Create dashboard:", msg)
                sys.exit(1)

        await ws.send(json.dumps({
            "id": 2,
            "type": "lovelace/config/save",
            "url_path": args.url_path,
            "config": dashboard_config,
        }))
        msg = json.loads(await ws.recv())
        ok = msg.get("type") == "result" and msg.get("success")
        print("Dashboard salvata:", ok, f"-> {ha_url}/{args.url_path}")
        if not ok:
            print(msg)
            sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (urllib.error.URLError, Exception) as err:  # noqa: BLE001
        print("Errore:", err)
        sys.exit(1)
