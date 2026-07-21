"""
HPE scraper.

Zdroj dat: verejne HPE Software Delivery Repository (SDR), stejny zdroj,
ktery pouziva Service Pack for ProLiant (SPP) / Smart Update Manager.
Neni potreba prihlaseni.

    https://downloads.linux.hpe.com/SDR/repo/spp-<generace>/<verze>/manifest/system.xml
    https://downloads.linux.hpe.com/SDR/repo/spp-<generace>/<verze>/manifest/meta.xml

`system.xml` obsahuje seznam systemu (serverovych modelu) a ke kazdemu z nich
seznam ID komponent (product_version), ktere jsou pro dany system relevantni.
`meta.xml` obsahuje popis kazde komponenty (nazev, verze, datum vydani,
kategorie, popis) podle jejiho ID.

HPE ma pro kazdou generaci serveru samostatnou vetev SPP repozitare:
spp-gen10 (pokryva i Gen10 Plus), spp-gen11, spp-gen12. Vybirame vzdy
nejnovejsi verzi (slozka s nejvyssim datem v adresarovem vypisu).
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List
from xml.etree import ElementTree as ET

from common import Update, get, parse_date_loose

logger = logging.getLogger("scrape_hpe")

SDR_BASE = "https://downloads.linux.hpe.com/SDR/repo"

# Mapovani "generace" ze config/devices.yaml na SPP repozitar.
# Gen10 a Gen10 Plus sdileji stejnou vetev - rozlisuji se az podle nazvu
# systemu v system.xml ("... Gen10 Plus Server" vs "... Gen10 Server").
GENERATION_TO_REPO = {
    "gen10": "spp-gen10",
    "gen10 plus": "spp-gen10",
    "gen11": "spp-gen11",
    "gen12": "spp-gen12",
}

_DIR_LINK_RE = re.compile(r'href="([0-9][0-9A-Za-z_.\-]*)/"')


def _latest_version_dir(repo: str) -> str | None:
    url = f"{SDR_BASE}/{repo}/"
    try:
        resp = get(url)
    except Exception as exc:  # noqa: BLE001
        logger.error("Nelze nacist repozitar %s: %s", url, exc)
        return None
    versions = sorted(set(_DIR_LINK_RE.findall(resp.text)))
    if not versions:
        return None
    return versions[-1]  # verze jsou ve formatu RRRR.MM.DD.NN, razeni retezcem funguje


def _fetch_xml(url: str) -> ET.Element | None:
    try:
        resp = get(url)
        return ET.fromstring(resp.content)
    except Exception as exc:  # noqa: BLE001
        logger.error("Nelze nacist/rozparsovat %s: %s", url, exc)
        return None


def _load_meta(repo: str, version: str) -> Dict[str, dict]:
    """Nacte manifest/meta.xml a vrati mapu product_id -> metadata."""
    url = f"{SDR_BASE}/{repo}/{version}/manifest/meta.xml"
    root = _fetch_xml(url)
    meta: Dict[str, dict] = {}
    if root is None:
        return meta

    for product in root.iter("product"):
        pid = product.get("id")
        pv = product.find("product_version")
        name_el = product.find("name/name_xlate")
        version_el = product.find("version")
        rd = product.find("release_date")
        cat_el = product.find("category/category_xlate")
        desc_el = product.find("description/description_xlate")

        release_date = ""
        if rd is not None:
            try:
                release_date = f"{rd.get('year')}-{int(rd.get('month')):02d}-{int(rd.get('day')):02d}"
            except (TypeError, ValueError):
                release_date = ""

        version_str = ""
        if version_el is not None:
            value = version_el.get("value", "")
            revision = version_el.get("revision", "")
            version_str = f"{value}({revision})" if revision else value

        meta[pid] = {
            "name": (name_el.text or "").strip() if name_el is not None else "",
            "version": version_str,
            "release_date": release_date,
            "category": (cat_el.text or "").strip() if cat_el is not None else "",
            "description": (desc_el.text or "").strip() if desc_el is not None else "",
        }
    return meta


def _load_systems(repo: str, version: str) -> List[dict]:
    """Nacte manifest/system.xml a vrati seznam systemu s jejich product_id."""
    url = f"{SDR_BASE}/{repo}/{version}/manifest/system.xml"
    root = _fetch_xml(url)
    systems: List[dict] = []
    if root is None:
        return systems

    for system in root.iter("system"):
        name_el = system.find("name/name_xlate")
        name = (name_el.text or "").strip() if name_el is not None else ""
        product_ids = [pv.find("id").get("product") for pv in system.findall("product_version") if pv.find("id") is not None]
        systems.append({"name": name, "product_ids": product_ids})
    return systems


def _system_matches(system_name: str, family: str, generation: str) -> bool:
    name = system_name.lower()
    if family.lower() not in name:
        return False
    gen = generation.lower()
    if gen == "gen10 plus":
        return "gen10 plus" in name
    if gen == "gen10":
        # "Gen10" ale NE "Gen10 Plus"
        return "gen10" in name and "gen10 plus" not in name
    return gen in name


def scrape(families: List[str], generations: List[str]) -> List[Update]:
    updates: List[Update] = []
    repos_needed = sorted({GENERATION_TO_REPO[g.lower()] for g in generations if g.lower() in GENERATION_TO_REPO})

    for repo in repos_needed:
        latest = _latest_version_dir(repo)
        if not latest:
            logger.warning("Repozitar %s: nenalezena zadna verze, preskakuji", repo)
            continue
        logger.info("HPE %s: pouzivam nejnovejsi SPP %s", repo, latest)

        systems = _load_systems(repo, latest)
        if not systems:
            logger.warning("%s: system.xml se nepodarilo nacist nebo je prazdny", repo)
            continue
        logger.info("%s: nacteno %d systemu (serverovych modelu) z manifestu", repo, len(systems))
        meta = _load_meta(repo, latest)
        if not meta:
            logger.warning("%s: meta.xml se nepodarilo nacist nebo je prazdny", repo)
            continue
        logger.info("%s: nacteno %d komponent (firmware/ovladacu) z manifestu", repo, len(meta))

        repo_had_any_match = False
        for family in families:
            for generation in generations:
                if GENERATION_TO_REPO.get(generation.lower()) != repo:
                    continue
                matching_systems = [s for s in systems if _system_matches(s["name"], family, generation)]
                if matching_systems:
                    repo_had_any_match = True
                for sys_entry in matching_systems:
                    for pid in sys_entry["product_ids"]:
                        info = meta.get(pid)
                        if not info or not info["name"]:
                            continue
                        upd = Update(
                            vendor="HPE",
                            family=family,
                            generation=generation,
                            update_id=info["version"] or "N/A",
                            release_date=info["release_date"],
                            description=info["description"][:500] or info["name"][:500],
                            category=info["category"],
                            source_url=f"https://support.hpe.com/connect/s/product?kmpmoid=&tab=driversAndSoftware",
                        )
                        updates.append(upd)

        if not repo_had_any_match:
            sample = [s["name"] for s in systems[:15]]
            logger.warning(
                "%s: pro zadanou kombinaci rodina/generace se nenaslo nic. Ukazka nazvu systemu v tomto "
                "repozitari (over, jestli sedi ocekavany format 'HPE ProLiant <rodina> <generace> Server'): %s",
                repo, sample,
            )

    # dedup
    seen = set()
    deduped = []
    for u in updates:
        if u.key() in seen:
            continue
        seen.add(u.key())
        deduped.append(u)

    logger.info("HPE: nalezeno %d relevantnich updatu", len(deduped))
    return deduped


if __name__ == "__main__":
    import json

    res = scrape(["DL380", "DL360"], ["Gen11", "Gen12"])
    print(json.dumps([u.to_dict() for u in res[:10]], ensure_ascii=False, indent=2))
