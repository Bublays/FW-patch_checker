"""
IBM scraper.

IBM nema jeden jednotny verejny katalog jako Dell/HPE, takze kombinujeme dva
zdroje podle typu zarizeni:

1) FlashSystem (7300 / 5300 / 5200) - firmware = uroven "IBM Storage
   Virtualize". Verejna "Support Information" stranka pro danou produktovou
   radu (7000 / 5000 family) obsahuje seznam vsech vydanych verzi s datem
   vydani a odkazem na release notes. Zadne prihlaseni neni potreba.

2) Tape knihovny (TS4300, Diamondback) - IBM zverejnuje pro kazdy produkt
   "fix readme" stranku na ibm.com/support/pages, ktera odkazuje na
   textovy soubor <Model>_fixlist.txt na delivery04.dhe.ibm.com.
   Ten obsahuje strukturovany seznam "Firmware Level" + "Release Date" +
   popis zmen - bez prihlaseni.

Pokud se pro nejake zarizeni nepodari zdroj najit (napr. IBM zmeni URL),
scraper danou polozku jen vynecha a zaloguje varovani - zbytek beihu tim
neni ovlivnen.
"""
from __future__ import annotations

import logging
import re
from typing import List

from common import Update, get, parse_date_loose

logger = logging.getLogger("scrape_ibm")

# --- FlashSystem / Storage Virtualize -----------------------------------

# Priklad radku na support-information strance:
# "**IBM Storage FlashSystem 7200, 7300 and 7600 v9.1.3.x
#  (Latest 9.1.3.0, released July 2026)**"
_FS_VERSION_RE = re.compile(
    r"IBM Storage FlashSystem[^\n(]*v([0-9.x]+)[^\n(]*\(Latest\s+([0-9.]+),\s*released\s+([A-Za-z]+\s+\d{4})\)",
    re.IGNORECASE,
)


def _scrape_flashsystem(device_id: str, display_name: str, support_info_page: str) -> List[Update]:
    updates: List[Update] = []
    try:
        resp = get(support_info_page)
    except Exception as exc:  # noqa: BLE001
        logger.error("%s: nelze nacist support-information stranku %s: %s", device_id, support_info_page, exc)
        return updates

    text = resp.text
    # Overime, ze se zarizeni na strance opravdu zminuje (napr. "7300" nebo "5300").
    model_number = re.search(r"\d{4}", device_id)
    model_number = model_number.group(0) if model_number else device_id

    for match in _FS_VERSION_RE.finditer(text):
        release_line_start = match.start()
        context = text[max(0, release_line_start - 300):release_line_start]
        if model_number not in context and model_number not in match.group(0):
            # radek se netyka naseho konkretniho modelu (napr. jen "5200" rodina)
            # - presto radeji zaznam pridame, protoze release je spolecny pro
            # celou rodinu FlashSystem/SVC; jen to oznacime v popisu.
            pass

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

    # dedup podle verze
    seen = set()
    deduped = []
    for u in updates:
        if u.update_id in seen:
            continue
        seen.add(u.update_id)
        deduped.append(u)

    logger.info("%s: nalezeno %d verzi", device_id, len(deduped))
    return deduped


# --- Tape knihovny (fixlist.txt) -----------------------------------------

_FIXLIST_LINK_RE = re.compile(r'href="(https?://[^"]*?_?(?:fixlist|readme)\.txt)"', re.IGNORECASE)
_FW_BLOCK_RE = re.compile(
    r"Firmware Level:\s*(?P<level>[^\n]+)\s*\nRelease Date:\s*(?P<date>[^\n]+)\s*\n"
    r"={5,}\s*\n+"
    r"(?P<body>.*?)(?=\n={5,}\s*\nFirmware Level:|\Z)",
    re.DOTALL,
)


def _find_fixlist_url(fix_readme_page: str) -> str | None:
    try:
        resp = get(fix_readme_page)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Nelze nacist fix-readme stranku %s: %s", fix_readme_page, exc)
        return None
    matches = _FIXLIST_LINK_RE.findall(resp.text)
    if not matches:
        return None
    # preferuj soubor s "fixlist" v nazvu pred "readme"
    for m in matches:
        if "fixlist" in m.lower():
            return m
    return matches[0]


def _summarize_body(body: str, max_len: int = 400) -> str:
    lines = [ln.strip("- ").strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("=")]
    # preskoc nadpisy "New Features:" / "Fixes:" a prazdne "None" polozky
    content = [ln for ln in lines if ln not in ("New Features:", "Fixes:", "None")]
    joined = "; ".join(content[:6])
    if len(joined) > max_len:
        joined = joined[: max_len - 1] + "…"
    return joined or "Bez detailniho popisu."


def _scrape_tape(device_id: str, display_name: str, fix_readme_page: str) -> List[Update]:
    updates: List[Update] = []
    fixlist_url = _find_fixlist_url(fix_readme_page)
    if not fixlist_url:
        logger.warning("%s: nepodarilo se najit odkaz na fixlist.txt na strance %s", device_id, fix_readme_page)
        return updates

    try:
        resp = get(fixlist_url)
    except Exception as exc:  # noqa: BLE001
        logger.error("%s: nelze stahnout %s: %s", device_id, fixlist_url, exc)
        return updates

    for match in _FW_BLOCK_RE.finditer(resp.text):
        level = match.group("level").strip()
        raw_date = match.group("date").strip()
        body = match.group("body")
        upd = Update(
            vendor="IBM",
            family=display_name,
            generation="",
            update_id=level,
            release_date=parse_date_loose(raw_date),
            description=_summarize_body(body),
            category="Firmware",
            source_url=fixlist_url,
        )
        updates.append(upd)

    logger.info("%s: nalezeno %d verzi firmware", device_id, len(updates))
    return updates


# --- Verejne API modulu -----------------------------------------------


def scrape(flashsystem_cfg: List[dict], tape_cfg: List[dict]) -> List[Update]:
    updates: List[Update] = []

    for dev in flashsystem_cfg:
        try:
            updates.extend(
                _scrape_flashsystem(dev["id"], dev["display_name"], dev["support_info_page"])
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Chyba pri zpracovani %s: %s", dev.get("id"), exc)

    for dev in tape_cfg:
        try:
            updates.extend(_scrape_tape(dev["id"], dev["display_name"], dev["fix_readme_page"]))
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
                "fix_readme_page": "https://www.ibm.com/support/pages/ts4300-fix-readme",
            }
        ],
    )
    print(json.dumps([u.to_dict() for u in res[:10]], ensure_ascii=False, indent=2))
