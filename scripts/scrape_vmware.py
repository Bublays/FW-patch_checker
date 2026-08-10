"""
VMware / Broadcom scraper.

Zdroj: verejne Broadcom Knowledge Base clanky se seznamem vsech vydanych
verzi/build cisel pro dany produkt (napr. clanek "Build numbers and versions
of VMware ESXi/ESX"). Zadne prihlaseni neni potreba - jen samotne STAZENI
patche pres Fix Central login vyzaduje, seznam verzi + data vydani je
verejny.

Struktura stranky: vic tabulek za sebou, kazde predchazi nadpis (h2/h3) s
nazvem "major verze" (napr. "ESXi 8.0", "vCenter Server 7.0"). Historie
sahá az k rokum ~2007-2009, coz je pro nas prilis mnoho starych zaznamu -
podle config/devices/vmware.yaml (klic "versions") zpracovavame jen tabulky,
jejichz nadpis obsahuje jeden z pozadovanych retezcu.

Sloupce v tabulkach se mezi strankami/verzemi mirne lisi (napr. vCenter 9.x
tabulka nema samostatny sloupec "Release name", jen "Version"; ESXi tabulky
maji navic "Available as"). Mapujeme proto sloupce podle textu hlavicky
tabulky, ne podle pevne pozice.
"""
from __future__ import annotations

import html as html_module
import logging
import re
from typing import Dict, List

from common import Update, get, parse_date_loose

logger = logging.getLogger("scrape_vmware")

_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_RE = re.compile(r"<h[1-4][^>]*>(.*?)</h[1-4]>", re.IGNORECASE | re.DOTALL)
_TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.IGNORECASE | re.DOTALL)

# Ruzne nazvy sloupcu napric strankami/verzemi, ktere mapujeme na nas
# jednotny vyznam. Klic je nas vyznam, hodnoty jsou mozne (lowercase) texty
# hlavicky sloupce.
_COLUMN_ALIASES = {
    "name": ("release name", "version"),
    "version": ("version",),
    "date": ("release date", "date"),
    "build": ("build number", "build", "build / release notes"),
}


def _strip_tags(fragment: str, tag_replacement: str = "") -> str:
    """Odstrani HTML tagy a rozbali entity. Vychozi bez nahrady mezerou -
    bunky tabulky maji verze/cisla casto rozdelena do vic <a> tagu a chceme
    je slozit zpatky dohromady bez mezer navic (viz stejny trik u IBM)."""
    text = _TAG_RE.sub(tag_replacement, fragment)
    return html_module.unescape(text)


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _find_heading_before(page_text: str, pos: int) -> str:
    """Vrati text posledniho nadpisu (h1-h4) pred pozici `pos` v HTML."""
    heading = ""
    for m in _HEADING_RE.finditer(page_text, 0, pos):
        heading = _collapse_ws(_strip_tags(m.group(1), tag_replacement=" "))
    return heading


def _parse_table(table_html: str) -> List[Dict[str, str]]:
    """Rozparsuje jednu HTML tabulku na seznam radku namapovanych podle
    hlavicky (prvni radek s bunkami = hlavicka)."""
    rows_out: List[Dict[str, str]] = []
    header: List[str] | None = None

    for row_html in _ROW_RE.findall(table_html):
        raw_cells = _CELL_RE.findall(row_html)
        # tag_replacement="" - viz komentar u _strip_tags: cisla verzi bejvaji
        # rozdelena inline <a> odkazy a nechceme do nich vnaset mezery navic.
        cells = [_collapse_ws(_strip_tags(c, tag_replacement="")) for c in raw_cells]
        if not any(cells):
            continue

        if header is None:
            header = [c.lower() for c in cells]
            continue

        row: Dict[str, str] = {}
        for key, aliases in _COLUMN_ALIASES.items():
            value = ""
            for alias in aliases:
                if alias in header:
                    idx = header.index(alias)
                    if idx < len(cells) and cells[idx]:
                        value = cells[idx]
                        break
            row[key] = value
        # fallback, kdyby se hlavicka vubec nenasla - prvni bunka jako "name"
        if not row.get("name") and cells:
            row["name"] = cells[0]
        rows_out.append(row)

    return rows_out


def _scrape_page(device_id: str, display_name: str, url: str, versions: List[str], category: str) -> List[Update]:
    updates: List[Update] = []
    try:
        resp = get(url)
    except Exception as exc:  # noqa: BLE001
        logger.error("%s: nelze nacist %s: %s", device_id, url, exc)
        return updates

    page_text = resp.text
    wanted = [v.lower() for v in versions]

    tables_total = 0
    tables_matched = 0
    matched_headings: List[str] = []

    for tmatch in _TABLE_RE.finditer(page_text):
        tables_total += 1
        heading = _find_heading_before(page_text, tmatch.start())
        if not heading or not any(w in heading.lower() for w in wanted):
            continue
        tables_matched += 1
        matched_headings.append(heading)

        for row in _parse_table(tmatch.group(1)):
            version = row.get("name") or row.get("version") or ""
            if not version:
                continue
            build = row.get("build", "")
            description = f"{heading}"
            if build:
                description += f" (build {build})"

            upd = Update(
                vendor="VMware",
                family=display_name,
                generation=heading,
                update_id=version,
                release_date=parse_date_loose(row.get("date", "").replace("/", "-")),
                description=description,
                category=category,
                source_url=url,
            )
            updates.append(upd)

    if tables_matched == 0:
        logger.warning(
            "%s: na strance %s se nenasla zadna tabulka odpovidajici pozadovanym verzim %s "
            "(celkem %d tabulek na strance - zkontroluj, jestli se nezmenil format nadpisu)",
            device_id, url, versions, tables_total,
        )
    else:
        logger.info(
            "%s: nalezeno %d zaznamu z %d tabulek (%s)",
            device_id, len(updates), tables_matched, matched_headings,
        )

    # dedup
    seen = set()
    deduped = []
    for u in updates:
        if u.key() in seen:
            continue
        seen.add(u.key())
        deduped.append(u)
    return deduped


def scrape(cfg: dict) -> List[Update]:
    """Verejne rozhrani scraperu - `cfg` je cely obsah config/devices/vmware.yaml
    (klic 'products'). Stejny podpis `scrape(cfg)` maji vsechny
    scrape_<vyrobce>.py moduly, aby si je run_all.py mohl sam najit a zavolat."""
    updates: List[Update] = []
    for dev in cfg.get("products", []):
        try:
            updates.extend(
                _scrape_page(
                    dev["id"],
                    dev["display_name"],
                    dev["source_page"],
                    dev.get("versions", []),
                    dev.get("category", "Firmware"),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Chyba pri zpracovani %s: %s", dev.get("id"), exc)

    logger.info("VMware: celkem nalezeno %d relevantnich updatu", len(updates))
    return updates


if __name__ == "__main__":
    import json

    res = scrape(
        {
            "products": [
                {
                    "id": "ESXi",
                    "display_name": "VMware ESXi",
                    "source_page": "https://knowledge.broadcom.com/external/article/316595/build-numbers-and-versions-of-vmware-esx.html",
                    "versions": ["8.0", "9.0", "9.1"],
                    "category": "Firmware/Hypervisor",
                }
            ]
        }
    )
    print(json.dumps([u.to_dict() for u in res[:10]], ensure_ascii=False, indent=2))
