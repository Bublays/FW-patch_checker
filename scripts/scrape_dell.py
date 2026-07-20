"""
Dell scraper.

Zdroj dat: verejny Dell Enterprise katalog (Catalog.xml.gz), stejny soubor,
ktery pouziva Dell Repository Manager / OpenManage / Dell Command Update.
Neni potreba prihlaseni.

    https://downloads.dell.com/catalog/Catalog.xml.gz

Katalog obsahuje VSECHNY Dell komponenty (BIOS, firmware, ovladace, aplikace)
pro vsechny podporovane systemy - je velky (typicky 150-250 MB po rozbaleni).
Filtrujeme podle <SupportedSystems><Brand><Model Display="..."> a beytelnou
kategorii (BIOS / Firmware) necháváme v poli `category`, aby si uzivatel mohl
v UI vyfiltrovat i ovladace, pokud bude chtit.
"""
from __future__ import annotations

import gzip
import io
import logging
import xml.etree.ElementTree as ET
from typing import Iterable, List

from common import Update, get, parse_date_loose

logger = logging.getLogger("scrape_dell")

CATALOG_URL = "https://downloads.dell.com/catalog/Catalog.xml.gz"
BASE_DOWNLOAD_URL = "https://downloads.dell.com/"


def _download_catalog() -> ET.Element:
    logger.info("Stahuji Dell katalog: %s", CATALOG_URL)
    resp = get(CATALOG_URL)
    logger.info("Katalog stazen (%.1f MB), rozbaluji...", len(resp.content) / 1_000_000)
    with gzip.GzipFile(fileobj=io.BytesIO(resp.content)) as gz:
        data = gz.read()
    logger.info("Rozbaleno (%.1f MB), parsuji XML...", len(data) / 1_000_000)
    return ET.fromstring(data)


def _matches_model(component: ET.Element, models: Iterable[str]) -> str | None:
    """Vrati presny nazev modelu (Display), pokud komponenta patri mezi sledovana zarizeni."""
    supported = component.find("SupportedSystems")
    if supported is None:
        return None
    for brand in supported.findall("Brand"):
        for model_el in brand.findall("Model"):
            display = (model_el.get("Display") or "").strip()
            if not display:
                display_el = model_el.find("Display")
                display = (display_el.text or "").strip() if display_el is not None else ""
            for wanted in models:
                # "PowerEdge R740" musi byt podretezcem, napr. "PowerEdge R740" == "PowerEdge R740"
                # nebo katalog obcas uvadi jen "R740".
                if wanted.lower() in display.lower() or wanted.split()[-1].lower() in display.lower():
                    return display
    return None


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def scrape(models: List[str]) -> List[Update]:
    updates: List[Update] = []
    try:
        root = _download_catalog()
    except Exception as exc:  # noqa: BLE001
        logger.error("Nepodarilo se stahnout/rozparsovat Dell katalog: %s", exc)
        return updates

    software = root.find("SoftwareComponent")
    # SoftwareComponent je opakovany element primo pod <Manifest>, ne obalka.
    components = root.findall("SoftwareComponent") if software is not None else root.findall(".//SoftwareComponent")
    logger.info("Katalog obsahuje %d komponent, filtruji podle modelu %s", len(components), models)

    seen = set()
    for comp in components:
        matched_model = _matches_model(comp, models)
        if not matched_model:
            continue

        name = _text(comp.find("Name/Display"))
        category = _text(comp.find("Category/Display"))
        dell_version = comp.get("dellVersion") or comp.get("vendorVersion") or ""
        release_date = parse_date_loose(comp.get("releaseDate", ""))
        path = comp.get("path", "")
        source_url = BASE_DOWNLOAD_URL + path if path else ""
        important_info = comp.find("ImportantInfo")
        if important_info is not None and important_info.get("URL"):
            source_url = important_info.get("URL")

        description = name
        important_notes = _text(comp.find("Description/Display"))
        if important_notes and important_notes != name:
            description = f"{name} — {important_notes}"

        upd = Update(
            vendor="Dell",
            family=matched_model,
            generation="",
            update_id=dell_version or "N/A",
            release_date=release_date,
            description=description[:500],
            category=category,
            source_url=source_url,
        )
        if upd.key() in seen:
            continue
        seen.add(upd.key())
        updates.append(upd)

    logger.info("Dell: nalezeno %d relevantnich updatu", len(updates))
    return updates


if __name__ == "__main__":
    import json

    res = scrape(["PowerEdge R440", "PowerEdge R740", "PowerEdge T140"])
    print(json.dumps([u.to_dict() for u in res[:10]], ensure_ascii=False, indent=2))
