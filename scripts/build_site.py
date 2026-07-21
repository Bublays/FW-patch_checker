"""
Vygeneruje staticky web (docs/) pro GitHub Pages z data/latest.json.
Jeden soubor index.html se zabudovanym JS (zadne externi zavislosti -> funguje
i bez pristupu k CDN), filtr podle vyrobce/rodiny a razeni podle data.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(ROOT, "data", "latest.json")
DOCS_DIR = os.path.join(ROOT, "docs")

TEMPLATE = """<!doctype html>
<html lang="cs">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FW checker — přehled firmware a patchů</title>
<style>
  :root {{
    --bg: #f5f6f8;
    --surface: #ffffff;
    --border: #e4e6ea;
    --text: #1c1f26;
    --text-muted: #6b7280;
    --accent: #3557e8;
    --hpe: #01a982;
    --hpe-bg: #e3f8f1;
    --dell: #0076ce;
    --dell-bg: #e6f2fb;
    --ibm: #111318;
    --ibm-bg: #eceef2;
    --radius: 10px;
    --shadow: 0 1px 2px rgba(16, 24, 40, .04), 0 1px 3px rgba(16, 24, 40, .06);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    margin: 0;
    padding: 2rem clamp(1rem, 4vw, 2.5rem) 3rem;
    max-width: 1280px;
    margin-inline: auto;
    background: var(--bg);
    color: var(--text);
  }}
  h1 {{ font-size: 1.55rem; font-weight: 700; margin: 0 0 .3rem; letter-spacing: -.01em; }}
  .meta {{ color: var(--text-muted); font-size: .85rem; margin-bottom: 1.5rem; }}

  .cards {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
    gap: .45rem;
    margin-bottom: 1rem;
  }}
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-left: 3px solid var(--card-color, var(--accent));
    border-radius: 7px;
    padding: .5rem .7rem;
  }}
  .card .num {{ font-size: 1.05rem; font-weight: 700; line-height: 1.1; }}
  .card .label {{ font-size: .65rem; color: var(--text-muted); margin-top: .1rem; text-transform: uppercase; letter-spacing: .03em; }}
  .card.hpe {{ --card-color: var(--hpe); }}
  .card.dell {{ --card-color: var(--dell); }}
  .card.ibm {{ --card-color: var(--ibm); }}

  .controls {{
    display: flex;
    gap: .6rem;
    flex-wrap: wrap;
    margin-bottom: 1rem;
    position: sticky;
    top: 0;
    background: var(--bg);
    padding: .6rem 0;
    z-index: 5;
  }}
  .controls::after {{
    content: "";
    position: absolute;
    left: 0; right: 0; bottom: -1px;
    height: 1px;
    background: linear-gradient(to right, var(--border), transparent 85%);
  }}
  select, input {{
    padding: .5rem .7rem;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--surface);
    font-size: .87rem;
    color: var(--text);
  }}
  input[type="search"] {{ flex: 1 1 220px; min-width: 180px; }}
  select {{ min-width: 140px; }}
  select:focus, input:focus {{ outline: 2px solid var(--accent); outline-offset: 1px; }}

  .table-wrap {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    box-shadow: var(--shadow);
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: .87rem; table-layout: fixed; }}
  th, td {{ text-align: left; padding: .65rem .75rem; border-bottom: 1px solid var(--border); vertical-align: top; overflow: hidden; text-overflow: ellipsis; }}
  col.c-vendor {{ width: 9%; }}
  col.c-family {{ width: 13%; }}
  col.c-generation {{ width: 8%; }}
  col.c-update {{ width: 12%; }}
  col.c-date {{ width: 14%; }}
  col.c-desc {{ width: 36%; }}
  col.c-source {{ width: 8%; }}
  th {{
    cursor: pointer; user-select: none;
    position: sticky; top: 52px;
    background: #fafbfc;
    color: var(--text-muted);
    font-weight: 600;
    font-size: .76rem;
    text-transform: uppercase;
    letter-spacing: .03em;
    white-space: nowrap;
  }}
  th:hover {{ color: var(--text); }}
  th .arrow {{ opacity: .5; margin-left: .2rem; font-size: .7rem; }}
  tbody tr {{ transition: background .1s ease; }}
  tbody tr:nth-child(even) {{ background: #fafbfc; }}
  tbody tr:hover {{ background: #eef2ff; }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tr.is-new td {{ background: #fff7e0; }}
  tr.is-new:hover td {{ background: #fdedb8; }}

  .badge {{
    display: inline-flex;
    align-items: center;
    padding: .2rem .55rem;
    border-radius: 999px;
    font-size: .74rem;
    font-weight: 600;
    white-space: nowrap;
  }}
  .badge.HPE {{ background: var(--hpe-bg); color: var(--hpe); }}
  .badge.Dell {{ background: var(--dell-bg); color: var(--dell); }}
  .badge.IBM {{ background: var(--ibm-bg); color: var(--ibm); }}

  .desc {{ color: var(--text); white-space: normal; }}
  .date-cell {{ white-space: nowrap; font-variant-numeric: tabular-nums; }}
  .desc-muted {{ color: var(--text-muted); }}
  a.src-link {{
    color: var(--accent); text-decoration: none; font-weight: 600; font-size: .82rem;
    white-space: nowrap;
  }}
  a.src-link:hover {{ text-decoration: underline; }}

  .empty {{ padding: 2.5rem; text-align: center; color: var(--text-muted); }}

  @media (max-width: 640px) {{
    .cards {{ grid-template-columns: repeat(2, 1fr); }}
    th {{ top: 96px; }}
  }}
</style>
</head>
<body>
<h1>Firmware &amp; patch checker — HPE / Dell / IBM</h1>
<div class="meta">Vygenerováno: {generated_at} · celkem záznamů: {count} · zdroj dat je stahován automaticky z veřejných portálů výrobců (bez přihlášení)</div>

<div class="cards" id="cards"></div>

<div class="controls">
  <input id="search" type="search" placeholder="Hledat (model, verze, popis)...">
  <select id="vendorFilter"><option value="">Všichni výrobci</option></select>
  <select id="familyFilter"><option value="">Všechny modely</option></select>
</div>

<div class="table-wrap">
<table id="tbl">
  <colgroup>
    <col class="c-vendor"><col class="c-family"><col class="c-generation">
    <col class="c-update"><col class="c-date"><col class="c-desc"><col class="c-source">
  </colgroup>
  <thead>
    <tr>
      <th data-key="vendor">Výrobce</th>
      <th data-key="family">Zařízení</th>
      <th data-key="generation">Generace</th>
      <th data-key="update_id">Číslo update</th>
      <th data-key="release_date">Datum vydání</th>
      <th data-key="description">Popis</th>
      <th>Zdroj</th>
    </tr>
  </thead>
  <tbody></tbody>
</table>
<div class="empty" id="emptyMsg" style="display:none">Žádné záznamy neodpovídají filtru.</div>
</div>

<script>
const DATA = {data_json};

let sortKey = "release_date";
let sortDir = -1;

function renderCards() {{
  const counts = {{}};
  for (const r of DATA.updates) counts[r.vendor] = (counts[r.vendor] || 0) + 1;
  const order = ["HPE", "Dell", "IBM"];
  const cardsEl = document.getElementById("cards");
  cardsEl.innerHTML = `
    <div class="card"><div class="num">${{DATA.updates.length}}</div><div class="label">Celkem záznamů</div></div>
    ${{order.filter(v => counts[v]).map(v => `
      <div class="card ${{v.toLowerCase()}}"><div class="num">${{counts[v]}}</div><div class="label">${{v}}</div></div>
    `).join("")}}
  `;
}}

function render() {{
  const search = document.getElementById("search").value.toLowerCase();
  const vendor = document.getElementById("vendorFilter").value;
  const family = document.getElementById("familyFilter").value;

  let rows = DATA.updates.filter(r => {{
    if (vendor && r.vendor !== vendor) return false;
    if (family && r.family !== family) return false;
    if (search) {{
      const hay = (r.vendor + " " + r.family + " " + r.generation + " " + r.update_id + " " + r.description).toLowerCase();
      if (!hay.includes(search)) return false;
    }}
    return true;
  }});

  rows.sort((a, b) => {{
    const av = (a[sortKey] || "").toString();
    const bv = (b[sortKey] || "").toString();
    return av < bv ? -1 * sortDir : av > bv ? 1 * sortDir : 0;
  }});

  document.querySelectorAll("th[data-key]").forEach(th => {{
    const key = th.dataset.key;
    const label = th.dataset.label || th.textContent.replace(/[▲▼]/g, "").trim();
    th.dataset.label = label;
    th.innerHTML = label + (key === sortKey ? `<span class="arrow">${{sortDir === 1 ? "▲" : "▼"}}</span>` : "");
  }});

  const tbody = document.querySelector("#tbl tbody");
  tbody.innerHTML = "";
  document.getElementById("emptyMsg").style.display = rows.length ? "none" : "block";
  document.querySelector(".table-wrap").style.display = rows.length ? "" : "none";

  for (const r of rows) {{
    const tr = document.createElement("tr");
    if (DATA.new_keys && DATA.new_keys.includes(r.key)) tr.classList.add("is-new");
    tr.innerHTML = `
      <td><span class="badge ${{r.vendor}}">${{r.vendor}}</span></td>
      <td>${{r.family}}</td>
      <td>${{r.generation || "—"}}</td>
      <td>${{r.update_id}}</td>
      <td class="date-cell">${{r.release_date || "?"}}</td>
      <td class="desc">${{r.description || ""}}</td>
      <td>${{r.source_url ? `<a class="src-link" href="${{r.source_url}}" target="_blank" rel="noopener">odkaz →</a>` : `<span class="desc-muted">—</span>`}}</td>
    `;
    tbody.appendChild(tr);
  }}
}}

function populateFilters() {{
  const vendors = [...new Set(DATA.updates.map(r => r.vendor))].sort();
  const families = [...new Set(DATA.updates.map(r => r.family))].sort();
  const vendorSel = document.getElementById("vendorFilter");
  const familySel = document.getElementById("familyFilter");
  for (const v of vendors) {{
    const o = document.createElement("option"); o.value = v; o.textContent = v; vendorSel.appendChild(o);
  }}
  for (const f of families) {{
    const o = document.createElement("option"); o.value = f; o.textContent = f; familySel.appendChild(o);
  }}
}}

document.querySelectorAll("th[data-key]").forEach(th => {{
  th.addEventListener("click", () => {{
    const key = th.dataset.key;
    if (sortKey === key) sortDir *= -1; else {{ sortKey = key; sortDir = 1; }}
    render();
  }});
}});
document.getElementById("search").addEventListener("input", render);
document.getElementById("vendorFilter").addEventListener("change", render);
document.getElementById("familyFilter").addEventListener("change", render);

renderCards();
populateFilters();
render();
</script>
</body>
</html>
"""


def main() -> None:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    os.makedirs(DOCS_DIR, exist_ok=True)

    # zkopiruj syrova data vedle stranky, aby sla i strojove stahnout / auditovat
    shutil.copyfile(DATA_PATH, os.path.join(DOCS_DIR, "data.json"))

    generated_raw = data.get("generated_at") or dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    # "2026-07-21T05:49:26Z" -> "2026-07-21 05:49:26 UTC" (datum a cas oddelene mezerou, citelnejsi)
    generated_display = generated_raw.replace("T", " ").replace("Z", " UTC").strip()

    html = TEMPLATE.format(
        generated_at=generated_display,
        count=data.get("count", len(data.get("updates", []))),
        data_json=json.dumps(data, ensure_ascii=False),
    )
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Web vygenerovan do {DOCS_DIR} ({data.get('count', 0)} zaznamu)")


if __name__ == "__main__":
    main()
