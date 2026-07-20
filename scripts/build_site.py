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
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 2rem; max-width: 1200px; margin-inline: auto; }}
  h1 {{ font-size: 1.4rem; margin-bottom: .25rem; }}
  .meta {{ color: #666; font-size: .85rem; margin-bottom: 1.5rem; }}
  .controls {{ display: flex; gap: .75rem; flex-wrap: wrap; margin-bottom: 1rem; }}
  select, input {{ padding: .4rem .6rem; border-radius: 6px; border: 1px solid #ccc; font-size: .9rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .88rem; }}
  th, td {{ text-align: left; padding: .5rem .6rem; border-bottom: 1px solid #e2e2e2; vertical-align: top; }}
  th {{ cursor: pointer; user-select: none; position: sticky; top: 0; background: Canvas; }}
  tr.is-new td {{ background: #fff8e1; }}
  .badge {{ display: inline-block; padding: .1rem .5rem; border-radius: 999px; font-size: .72rem; font-weight: 600; }}
  .badge.HPE {{ background: #e6f0ff; color: #0b5fff; }}
  .badge.Dell {{ background: #eaf7ea; color: #147a14; }}
  .badge.IBM {{ background: #f1e9ff; color: #5b2ec2; }}
  a {{ color: inherit; }}
  .empty {{ padding: 2rem; text-align: center; color: #777; }}
</style>
</head>
<body>
<h1>Firmware &amp; patch checker — HPE / Dell / IBM</h1>
<div class="meta">Vygenerováno: {generated_at} · celkem záznamů: {count} · zdroj dat je stahován automaticky z veřejných portálů výrobců (bez přihlášení)</div>

<div class="controls">
  <input id="search" type="search" placeholder="Hledat (model, verze, popis)...">
  <select id="vendorFilter"><option value="">Všichni výrobci</option></select>
  <select id="familyFilter"><option value="">Všechny modely</option></select>
</div>

<table id="tbl">
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

<script>
const DATA = {data_json};

let sortKey = "release_date";
let sortDir = -1;

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

  const tbody = document.querySelector("#tbl tbody");
  tbody.innerHTML = "";
  document.getElementById("emptyMsg").style.display = rows.length ? "none" : "block";

  for (const r of rows) {{
    const tr = document.createElement("tr");
    if (DATA.new_keys && DATA.new_keys.includes(r.key)) tr.classList.add("is-new");
    tr.innerHTML = `
      <td><span class="badge ${{r.vendor}}">${{r.vendor}}</span></td>
      <td>${{r.family}}</td>
      <td>${{r.generation || ""}}</td>
      <td>${{r.update_id}}</td>
      <td>${{r.release_date || "?"}}</td>
      <td>${{r.description || ""}}</td>
      <td>${{r.source_url ? `<a href="${{r.source_url}}" target="_blank" rel="noopener">odkaz</a>` : ""}}</td>
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

    html = TEMPLATE.format(
        generated_at=data.get("generated_at", dt.datetime.utcnow().isoformat()),
        count=data.get("count", len(data.get("updates", []))),
        data_json=json.dumps(data, ensure_ascii=False),
    )
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Web vygenerovan do {DOCS_DIR} ({data.get('count', 0)} zaznamu)")


if __name__ == "__main__":
    main()
