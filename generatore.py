import argparse
import os
import re
import sys


def estrai_base(entity_id, suffissi):
    for pref in ("climate.", "number.", "switch.", "button.", "sensor.", "binary_sensor."):
        if entity_id.startswith(pref):
            entity_id = entity_id[len(pref):]
            break
    for suf in suffissi:
        if entity_id.endswith(suf):
            entity_id = entity_id[:-len(suf)]
            break
    return entity_id


def leggi_base(clima, temp):
    base_c = estrai_base(clima, ("_climatizzazione",))
    base_t = estrai_base(temp, ("_temperatura_salvata",))
    if base_c != base_t:
        print(f"ERRORE: gli esempi indicano basi diverse ({base_c} vs {base_t})", file=sys.stderr)
        sys.exit(1)
    base = re.sub(r"_\d+$", "", base_c)
    return base, base_c


def entita_zona(base, i):
    dev = f"{base}_{i}"
    return {
        "dev": dev,
        "clima": f"climate.{dev}_climatizzazione",
        "temp_salvata": f"number.{dev}_temperatura_salvata",
        "modalita": f"switch.{dev}_modalita_centralizzata",
        "rinnovo": f"button.{dev}_rinnova_modalita_centralizzata",
        "messaggio": f"sensor.{dev}_ultimo_messaggio_esp_now",
    }


def nomi_helper(tag, i, campo):
    return f"input_number.{campo}_{tag}_{i}"


def build_apps(istanza, tag, n, base, soglia, attivo):
    lines = []
    lines.append(f"{istanza}:")
    lines.append(f"  module: riscaldamento")
    lines.append(f"  class: riscaldamento_centralizzato")
    lines.append(f"  numero_zone: {n}")
    lines.append(f"  soglia_pesi: {soglia}")
    lines.append(f"  attivo: {attivo}")
    for i in range(1, n + 1):
        e = entita_zona(base, i)
        lines.append(f"  zona{i}:")
        lines.append(f"    clima: {e['clima']}")
        lines.append(f"    temp_salvata: {e['temp_salvata']}")
        lines.append(f"    peso: {nomi_helper(tag, i, 'peso')}")
        lines.append(f"    inclusione: input_boolean.inclusione_{tag}_{i}")
        lines.append(f"    delta_squadra_giorno: {nomi_helper(tag, i, 'delta_squadra_giorno')}")
        lines.append(f"    delta_squadra_notte: {nomi_helper(tag, i, 'delta_squadra_notte')}")
        lines.append(f"    delta_spegnimento_giorno: {nomi_helper(tag, i, 'delta_spegnimento_giorno')}")
        lines.append(f"    delta_spegnimento_notte: {nomi_helper(tag, i, 'delta_spegnimento_notte')}")
        lines.append(f"    rinnovo_modalita: {e['rinnovo']}")
        lines.append(f"    modalita_centralizzata: {e['modalita']}")
    return "\n".join(lines)


def build_config(tag, n, soglia, attivo, base, feedback):
    lines = []
    lines.append("input_number:")
    lines.append(f"  {soglia.split('.')[1]}:")
    lines.append("    name: Soglia Pesi")
    lines.append("    min: 0")
    lines.append("    max: 10")
    lines.append("    step: 0.1")
    lines.append("    mode: slider")
    for campo in ("peso", "delta_squadra_giorno", "delta_squadra_notte", "delta_spegnimento_giorno", "delta_spegnimento_notte"):
        mn = 0
        mx = 5
        st = 0.5
        if campo == "peso":
            mn, mx, st = 0, 5, 0.5
        elif campo.startswith("delta_squadra"):
            mn, mx, st = 0, 2, 0.1
        elif campo.startswith("delta_spegnimento"):
            mn, mx, st = -1, 1, 0.1
        for i in range(1, n + 1):
            nome = f"{campo}_{tag}_{i}"
            lines.append(f"  {nome}:")
            lines.append(f"    name: {campo.replace('_', ' ').title()} {tag.upper()}{i}")
            lines.append(f"    min: {mn}")
            lines.append(f"    max: {mx}")
            lines.append(f"    step: {st}")
            lines.append("    mode: slider")

    lines.append("input_boolean:")
    lines.append(f"  {attivo.split('.')[1]}:")
    lines.append("    name: Attivo Centralizzato")
    for i in range(1, n + 1):
        lines.append(f"  inclusione_{tag}_{i}:")
        lines.append(f"    name: Inclusione {tag.upper()}{i}")

    if feedback:
        coll = estrai_base(feedback, ("_feedback_zona_1",))
        lines.append("template:")
        lines.append("  - sensor:")
        for i in range(1, n + 1):
            e = entita_zona(base, i)
            nome = f"Coerenza Zona {i} {tag.upper()}{i}"
            fb = f"binary_sensor.{coll}_feedback_zona_{i}"
            lines.append(f'      - name: "{nome}"')
            lines.append(f"        state: >-")
            lines.append(f"          {{{{ 'unavailable' if states('{e['messaggio']}') == 'unavailable' or states('{fb}') == 'unavailable' else ('ok' if ('ZONA_ON' in states('{e['messaggio']}') and states('{fb}') == 'on') or ('ZONA_OFF' in states('{e['messaggio']}') and states('{fb}') == 'off') else ('valvola_aperta' if states('{fb}') == 'on' else 'valvola_chiusa')) }}}}")
    return "\n".join(lines)


def build_lovelace(tag, n, base):
    lines = []
    lines.append("type: vertical-stack")
    lines.append("cards:")
    for i in range(1, n + 1):
        e = entita_zona(base, i)
        lines.append("  - type: entities")
        lines.append(f"    title: Zona {i} ({tag.upper()})")
        lines.append("    entities:")
        lines.append(f"      - entity: {e['clima']}")
        lines.append(f"      - entity: {e['temp_salvata']}")
        lines.append(f"      - entity: input_boolean.inclusione_{tag}_{i}")
        lines.append(f"      - entity: {nomi_helper(tag, i, 'peso')}")
        lines.append(f"      - entity: {nomi_helper(tag, i, 'delta_squadra_giorno')}")
        lines.append(f"      - entity: {nomi_helper(tag, i, 'delta_squadra_notte')}")
        lines.append(f"      - entity: {nomi_helper(tag, i, 'delta_spegnimento_giorno')}")
        lines.append(f"      - entity: {nomi_helper(tag, i, 'delta_spegnimento_notte')}")
        lines.append(f"      - entity: {e['modalita']}")
        lines.append(f"      - entity: {e['rinnovo']}")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Ricostruisce apps.yaml / configuration.yaml / lovelace dai pattern delle entita'")
    p.add_argument("--clima", required=True, help="esempio: climate.termostato_autonomo_1_climatizzazione")
    p.add_argument("--temp", required=True, help="esempio: number.termostato_autonomo_1_temperatura_salvata")
    p.add_argument("--zone", type=int, default=6)
    p.add_argument("--tag", required=True, help="etichetta helper: a, b, c, ...")
    p.add_argument("--istanza", default="riscaldamento_centralizzato")
    p.add_argument("--soglia", default="input_number.somma_dei_pesi")
    p.add_argument("--attivo", default="input_boolean.riscaldamento_centralizzato_attivo")
    p.add_argument("--feedback", default=None, help="esempio feedback valvola: binary_sensor.collettore_feedback_zona_1")
    p.add_argument("--outdir", default=None)
    args = p.parse_args()

    base, es_n = leggi_base(args.clima, args.temp)
    print(f"Base rilevata: '{base}' (esempio: {es_n}, zone: {args.zone}, tag: {args.tag})")

    apps = build_apps(args.istanza, args.tag, args.zone, base, args.soglia, args.attivo)
    conf = build_config(args.tag, args.zone, args.soglia, args.attivo, base, args.feedback)
    lov = build_lovelace(args.tag, args.zone, base)

    outdir = args.outdir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "OUT_GENERATORE")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "apps.yaml"), "w", encoding="utf-8") as f:
        f.write(apps + "\n")
    with open(os.path.join(outdir, "configuration.yaml"), "w", encoding="utf-8") as f:
        f.write(conf + "\n")
    with open(os.path.join(outdir, "lovelace.yaml"), "w", encoding="utf-8") as f:
        f.write(lov + "\n")
    print(f"Generati in: {outdir}")
    print("---- apps.yaml ----")
    print(apps)
    print("---- configuration.yaml ----")
    print(conf)
    print("---- lovelace.yaml ----")
    print(lov)


if __name__ == "__main__":
    main()
