// BUG CALENDARIO RISOLTO (2026-08-11): la tabella era righe=giorni x
// 24 colonne di ore (~670px, non stava nella card e l'overflow tornava
// a muoversi al click). Ora e' TRASPOSTA: righe=24 ore x colonne=7 giorni
// (~250px), resta dentro la card senza scroll. Vedi _render().
const DAYS = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"];
const VALUES = ["eco", "comfort", "autonomo"];
const LABELS = { eco: "E", comfort: "C", autonomo: "A" };
const COLORS = { eco: "#4caf50", comfort: "#ff9800", autonomo: "#607d8b" };
const TITLES = { eco: "Eco", comfort: "Comfort", autonomo: "Autonomo" };

class ClimaoroCalendario extends HTMLElement {
  setConfig(config) {
    if (!config.gruppo) {
      throw new Error("Serve il campo 'gruppo' (es. giorno/notte/servizi).");
    }
    this._config = config;
    this._gruppo = config.gruppo;
    this._appartamento = config.appartamento || "casa";
    this._entity = config.entity;
    this._state = null;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const next = hass.states[this._entity];
    if (next !== this._state) {
      this._state = next;
      this._render();
    }
  }

  _getCal() {
    if (!this._state || !this._state.attributes) return {};
    return this._state.attributes.calendario || {};
  }

  _cellValue(day, hour) {
    const row = (this._getCal())[day] || [];
    return row[hour] || "eco";
  }

  _cycle(day, hour) {
    if (!this._hass) return;
    const cur = this._cellValue(day, hour);
    const next = VALUES[(VALUES.indexOf(cur) + 1) % VALUES.length];
    this._hass.callService("climaoro", "set_calendario", {
      appartamento: this._appartamento,
      gruppo: this._gruppo,
      giorno: day,
      ora: hour,
      valore: next,
    });
  }

  _render() {
    this.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.style.cssText =
      "font-family:var(--primary-font-family);width:100%;box-sizing:border-box;";

    // Orientamento: righe = 24 ore, colonne = 7 giorni.
    // La tabella si estende su tutta la larghezza della card (table-layout
    // fixed), cosi' le celle riempiono lo spazio e i caratteri sono piu'
    // grandi.
    let html = "";
    const nome = this._config.title || this._config.nome;
    if (nome) {
      html +=
        "<div style='text-align:center;font-weight:600;font-size:17px;padding-bottom:8px'>" +
        nome +
        "</div>";
    }
    html +=
      "<table style='border-collapse:collapse;width:100%;table-layout:fixed'>";
    html += "<colgroup><col style='width:38px'></colgroup>";
    html += "<tr><th style='padding:2px 4px;font-size:13px'></th>";
    for (let d = 0; d < DAYS.length; d++) {
      html +=
        "<th style='padding:2px 2px;font-size:13px;font-weight:500;color:var(--secondary-text-color)'>" +
        DAYS[d] +
        "</th>";
    }
    html += "</tr>";

    for (let h = 0; h < 24; h++) {
      html +=
        "<tr><td style='padding:2px 4px;font-size:12px;color:var(--secondary-text-color);text-align:right'>" +
        h +
        "</td>";
      for (let d = 0; d < DAYS.length; d++) {
        const day = DAYS[d];
        const v = this._cellValue(day, h);
        html +=
          "<td style='padding:0'><button data-day='" +
          day +
          "' data-hour='" +
          h +
          "' title='" +
          day +
          " " +
          h +
          ":00 - " +
          TITLES[v] +
          "' style='width:100%;height:26px;font-size:14px;font-weight:600;border:none;border-radius:4px;margin:1px 0;cursor:pointer;color:#fff;padding:0;background:" +
          (COLORS[v] || COLORS.eco) +
          "'>" +
          (LABELS[v] || v) +
          "</button></td>";
      }
      html += "</tr>";
    }
    html += "</table>";

    wrap.innerHTML = html;
    wrap.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._cycle(btn.dataset.day, parseInt(btn.dataset.hour, 10));
      });
    });
    this.appendChild(wrap);
  }
}

customElements.define("climaoro-calendario", ClimaoroCalendario);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "climaoro-calendario",
  name: "Climaoro Calendario",
  description: "Calendario settimanale 7x24 eco/comfort/autonomo",
});
