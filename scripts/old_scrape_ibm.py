"""
IBM scraper.

IBM nema jeden jednotny verejny katalog jako Dell/HPE, takze kombinujeme tri
zdroje podle typu zarizeni (vsechny verejne, bez prihlaseni):

1) FlashSystem (7300 / 5300 / 5200) - firmware = uroven "IBM Storage
   Virtualize". Verejna "Support Information" stranka pro danou produktovou
   radu (7000 / 5000 family) obsahuje seznam vsech vydanych verzi s datem
   vydani. HTML struktura se mezi strankami mirne lisi (verze a datum bývaji
   nekdy v jednom, nekdy ve dvou sousednich <strong> tazich), takze parsujeme
   ohranicenym regexem, ktery mezeru mezi casti verze a datem toleruje.

2) Tape knihovny s plnou historii firmware (TS4300) - primarnim zdrojem je
   primy odkaz na "<Model>_fixlist.txt" na delivery04.dhe.ibm.com (cisty
   text, zadny HTML sum). Pokud by tento primy odkaz prestal fungovat,
   pouzije se jako zaloha verejna "fix readme" stranka na ibm.com/support,
   ktera stejny obsah zobrazuje primo vlozeny v tele stranky.

3) Tape knihovny bez samostatne historie (Diamondback) - IBM pro ne
   zverejnuje jen tabulku "Code Update Recommendation" (Minimum / Recommended
   / Latest Level s datem). Parsujeme primo HTML tabulku.

Pokud se pro nejake zarizeni nepodari zdroj najit (napr. IBM zmeni URL),
scraper danou polozku jen vynecha a zaloguje varovani - zbytek beihu tim
neni ovlivnen.
"""
from __future__ import annotations

import html as html_module
import logging
import re
from typing import List

from common import Update, get, parse_date_loose

logger = logging.getLogger("scrape_ibm")

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(fragment: str, tag_replacement: str = " ") -> str:
    """Odstrani HTML tagy a rozbali entity. Tagy nahrazuje mezerou/newline,
    aby se nespojovala slova z ruznych bunek/elementu do jednoho retezce."""
    text = _TAG_RE.sub(tag_replacement, fragment)
    return html_module.unescape(text)


def _collapse_ws(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


# --- FlashSystem / Storage Virtualize -----------------------------------

# Priklad (po ocisteni od HTML tagu, mezera muze byt i vic nez jedna - HTML
# strukturu autor stranky obcas rozdeli do dvou sousednich <strong> tagu):
# "IBM Storage FlashSystem 7200, 7300 and 7600 v9.1.3.x (Latest 9.1.3.0,
#  released July 2026)"
_FS_VERSION_RE = re.compile(
    r"IBM Storage FlashSystem[^()]{0,160}?v\s*([0-9.x]+)[^()]{0,60}?"
    r"\(Latest\s+([0-9.]+),\s*released\s+([A-Za-z]+\s+\d{4})\)",
    re.IGNORECASE | re.DOTALL,
)


def _scrape_flashsystem(device_id: str, display_name: str, support_info_page: str) -> List[Update]:
    updates: List[Update] = []
    try:
        resp = get(support_info_page)
    except Exception as exc:  # noqa: BLE001
        logger.error("%s: nelze nacist support-information stranku %s: %s", device_id, support_info_page, exc)
        return updates

    text = _strip_tags(resp.text)

    for match in _FS_VERSION_RE.finditer(text):
        train, latest, released = match.groups()
        release_date = parse_date_loose(released)
        upd = Update(
            vendor="IBM",
            family=display_name,
            generation="",
            update_id=latest,
            release_date=release_date,
            description=f"IBM Storage Virtualize {train} (nejnovejsi PTF {latest})",
            category="Firmware/Storage Virtualize",
            source_url=support_info_page,
        )
        updates.append(upd)

    seen = set()
    deduped = []
    for u in updates:
        if u.update_id in seen:
            continue
        seen.add(u.update_id)
        deduped.append(u)

    if not deduped:
        logger.warning(
            "%s: na strance %s se nenasla zadna verze - HTML struktura se mozna zmenila",
            device_id, support_info_page,
        )
    else:
        logger.info("%s: nalezeno %d verzi", device_id, len(deduped))
    return deduped


# --- Tape knihovny s plnou historii (fixlist.txt) -------------------------

_FW_BLOCK_RE = re.compile(
    r"Firmware Level:\s*(?P<level>[^\n]+)\s*\nRelease Date:\s*(?P<date>[^\n]+)\s*\n"
    r"={5,}\s*\n+"
    r"(?P<body>.*?)(?=\n={5,}\s*\nFirmware Level:|\Z)",
    re.DOTALL,
)

_PRE_BLOCK_RE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.IGNORECASE | re.DOTALL)


def _summarize_body(body: str, max_len: int = 400) -> str:
    lines = [ln.strip("- ").strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("=")]
    content = [ln for ln in lines if ln not in ("New Features:", "Fixes:", "None")]
    joined = "; ".join(content[:6])
    if len(joined) > max_len:
        joined = joined[: max_len - 1] + "…"
    return joined or "Bez detailniho popisu."


def _parse_fw_blocks(text: str) -> List[dict]:
    out = []
    for match in _FW_BLOCK_RE.finditer(text):
        out.append(
            {
                "level": match.group("level").strip(),
                "date": match.group("date").strip(),
                "body": match.group("body"),
            }
        )
    return out


def _scrape_tape_fixlist(device_id: str, display_name: str, cfg: dict) -> List[Update]:
    updates: List[Update] = []

    # 1) primy odkaz na cisty .txt soubor - preferovany zdroj (zadny HTML sum)
    txt_url = cfg.get("fixlist_txt_url")
    if txt_url:
        try:
            resp = get(txt_url)
            blocks = _parse_fw_blocks(resp.text)
            if blocks:
                for b in blocks:
                    updates.append(
                        Update(
                            vendor="IBM",
                            family=display_name,
                            generation="",
                            update_id=b["level"],
                            release_date=parse_date_loose(b["date"]),
                            description=_summarize_body(b["body"]),
                            category="Firmware",
                            source_url=txt_url,
                        )
                    )
                logger.info("%s: nalezeno %d verzi firmware (fixlist.txt)", device_id, len(updates))
                return updates
            logger.warning("%s: fixlist.txt (%s) neobsahoval ocekavany format, zkousim fallback", device_id, txt_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: nelze stahnout %s (%s), zkousim fallback", device_id, txt_url, exc)

    # 2) zaloha: fix-readme stranka na ibm.com/support s obsahem primo vlozenym v tele
    readme_page = cfg.get("fix_readme_page")
    if not readme_page:
        logger.error("%s: zadny funkcni zdroj dat (ani fixlist_txt_url, ani fix_readme_page)", device_id)
        return updates

    try:
        resp = get(readme_page)
    except Exception as exc:  # noqa: BLE001
        logger.error("%s: nelze nacist fix-readme stranku %s: %s", device_id, readme_page, exc)
        return updates

    pre_match = _PRE_BLOCK_RE.search(resp.text)
    raw = pre_match.group(1) if pre_match else resp.text
    text = html_module.unescape(_TAG_RE.sub("\n", raw))
    text = re.sub(r"\n{2,}", "\n", text)

    blocks = _parse_fw_blocks(text)
    for b in blocks:
        updates.append(
            Update(
                vendor="IBM",
                family=display_name,
                generation="",
                update_id=b["level"],
                release_date=parse_date_loose(b["date"]),
                description=_summarize_body(b["body"]),
                category="Firmware",
                source_url=readme_page,
            )
        )

    if not updates:
        logger.warning("%s: na fix-readme strance %s se nenasel zadny firmware blok", device_id, readme_page)
    else:
        logger.info("%s: nalezeno %d verzi firmware (fix-readme stranka)", device_id, len(updates))
    return updates


# --- Tape knihovny bez historie - tabulka "Code Update Recommendation" ---

_TABLE_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TABLE_CELL_RE = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.IGNORECASE | re.DOTALL)
_VERSION_DATE_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9.\-_]*)\s*\[\s*([A-Za-z]+\.?\s+\d{4})\s*\]")


def _scrape_recommendation_table(device_id: str, display_name: str, url: str) -> List[Update]:
    updates: List[Update] = []
    try:
        resp = get(url)
    except Exception as exc:  # noqa: BLE001
        logger.error("%s: nelze nacist stranku s doporucenymi urovnemi %s: %s", device_id, url, exc)
        return updates

    tier_labels = None
    for row_html in _TABLE_ROW_RE.findall(resp.text):
        raw_cells = _TABLE_CELL_RE.findall(row_html)
        # uvnitr jedne bunky nahrazujeme tagy prazdnym retezcem (ne mezerou) -
        # cisla verzi bejvaji rozdelena inline <a> odkazem, napr. "2<a>.11.0.4-C00</a>",
        # a s mezerou navic by se rozpadla na "2 .11.0.4-C00".
        cells = [_collapse_ws(_strip_tags(c, tag_replacement="")) for c in raw_cells]
        cells = [c for c in cells if c != ""]
        if not cells:
            continue

        if tier_labels is None:
            if any("level" in c.lower() for c in cells):
                tier_labels = cells
                continue
            # tabulka bez explicitni hlavicky - pouzij generické nazvy
            tier_labels = ["Produkt"] + [f"Uroven {i}" for i in range(1, len(cells))]

        if len(cells) < 2:
            continue

        product_label = cells[0]
        for i, cell in enumerate(cells[1:], start=1):
            m = _VERSION_DATE_RE.search(cell)
            if not m:
                continue
            version, raw_date = m.groups()
            tier = tier_labels[i] if i < len(tier_labels) else f"Sloupec {i}"
            updates.append(
                Update(
                    vendor="IBM",
                    family=f"{display_name} — {product_label}",
                    generation="",
                    update_id=version,
                    release_date=parse_date_loose(raw_date),
                    description=f"Uroven dle IBM doporuceni: {tier}",
                    category="Firmware",
                    source_url=url,
                )
            )

    if not updates:
        logger.warning("%s: v tabulce na %s se nenasel zadny radek s verzi/datem", device_id, url)
    else:
        logger.info("%s: nalezeno %d zaznamu z tabulky doporuceni", device_id, len(updates))
    return updates


# --- Verejne API modulu -----------------------------------------------


def scrape(
    flashsystem_cfg: List[dict],
    tape_fixlist_cfg: List[dict],
    tape_recommendation_cfg: List[dict],
) -> List[Update]:
    updates: List[Update] = []

    for dev in flashsystem_cfg:
        try:
            updates.extend(_scrape_flashsystem(dev["id"], dev["display_name"], dev["support_info_page"]))
        except Exception as exc:  # noqa: BLE001
            logger.error("Chyba pri zpracovani %s: %s", dev.get("id"), exc)

    for dev in tape_fixlist_cfg:
        try:
            updates.extend(_scrape_tape_fixlist(dev["id"], dev["display_name"], dev))
        except Exception as exc:  # noqa: BLE001
            logger.error("Chyba pri zpracovani %s: %s", dev.get("id"), exc)

    for dev in tape_recommendation_cfg:
        try:
            updates.extend(
                _scrape_recommendation_table(dev["id"], dev["display_name"], dev["recommendation_page"])
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Chyba pri zpracovani %s: %s", dev.get("id"), exc)

    logger.info("IBM: celkem nalezeno %d relevantnich updatu", len(updates))
    return updates


if __name__ == "__main__":
    import json

    res = scrape(
        [
            {
                "id": "FS7300",
                "display_name": "IBM FlashSystem 7300",
                "support_info_page": "https://www.ibm.com/support/pages/support-information-flashsystem-7000-family",
            }
        ],
        [
            {
                "id": "TS4300",
                "display_name": "IBM TS4300 Tape Library",
                "fixlist_txt_url": "https://delivery04.dhe.ibm.com/sar/CMA/STA/09qng/0/TS4300_fixlist.txt",
                "fix_readme_page": "https://www.ibm.com/support/pages/ts4300-fix-readme",
            }
        ],
        [
            {
                "id": "Diamondback",
                "display_name": "IBM Diamondback Tape Library",
                "recommendation_page": "https://www.ibm.com/support/pages/ibm-diamondback-code-update-recommendation",
            }
        ],
    )
    print(json.dumps([u.to_dict() for u in res[:10]], ensure_ascii=False, indent=2))
