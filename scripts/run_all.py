"""
Hlavni orchestracni skript. Podle konvence sam najde vsechny nakonfigurovane
vyrobce (config/devices/<vyrobce>.yaml) a k nim odpovidajici scrapery
(scripts/scrape_<vyrobce>.py), zavola jejich scrape(cfg) a vysledek ulozi do
data/latest.json. Zaroven udrzuje data/history.json (kvuli detekci "co je od
posledni kontroly nove").

Pridani noveho vyrobce se STEJNYM typem zdroje (napr. dalsi HPE rodina) =
uprava prislusneho config/devices/<vyrobce>.yaml, tento skript se nemeni.

Pridani UPLNE NOVEHO vyrobce (napr. Lenovo, VMware, Fortinet) vyzaduje:
  1) config/devices/<vyrobce>.yaml - seznam sledovanych zarizeni
  2) scripts/scrape_<vyrobce>.py   - modul s funkci scrape(cfg) -> list[Update]
     (cfg = cely obsah yaml souboru z bodu 1)
Nazev yaml souboru a nazev vyrobce v modulu (cast za "scrape_") musi byt
STEJNY - podle nej se moduly parujou s configy automaticky. Tento skript
(run_all.py) se pri pridani noveho vyrobce nemusi vubec upravovat.

Pouziti:
    python scripts/run_all.py

Vystupni kody:
    0 - probehlo v poradku (i kdyz nektery vyrobce selhal - viz log)
    1 - fatalni chyba (zadny config vyrobce se nenasel apod.)
"""
from __future__ import annotations

import datetime as dt
import glob
import importlib
import logging
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(__file__))

from common import Update, save_json, load_json, is_relevant_update  # noqa: E402

logger = logging.getLogger("run_all")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEVICES_DIR = os.path.join(ROOT, "config", "devices")
DATA_DIR = os.path.join(ROOT, "data")
LATEST_PATH = os.path.join(DATA_DIR, "latest.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")


def discover_vendor_configs() -> dict[str, dict]:
    """Najde config/devices/<vyrobce>.yaml soubory a vrati mapu
    {vyrobce: obsah_yaml}. Nazev vyrobce = nazev souboru bez pripony."""
    configs: dict[str, dict] = {}
    if not os.path.isdir(DEVICES_DIR):
        return configs
    for path in sorted(glob.glob(os.path.join(DEVICES_DIR, "*.yaml"))):
        vendor = os.path.splitext(os.path.basename(path))[0]
        with open(path, "r", encoding="utf-8") as f:
            configs[vendor] = yaml.safe_load(f) or {}
    return configs


def load_scraper(vendor: str):
    """Dynamicky importuje scripts/scrape_<vyrobce>.py podle konvence a
    vrati jeho funkci scrape(cfg). Vrati None (a zaloguje chybu), pokud
    modul/funkce chybi - dany vyrobce se pak jen preskoci."""
    module_name = f"scrape_{vendor}"
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        logger.error(
            "Pro vyrobce '%s' (config/devices/%s.yaml) neexistuje odpovidajici "
            "scripts/%s.py: %s",
            vendor, vendor, module_name, exc,
        )
        return None
    scrape_fn = getattr(module, "scrape", None)
    if scrape_fn is None:
        logger.error("scripts/%s.py neobsahuje verejnou funkci scrape(cfg)", module_name)
        return None
    return scrape_fn


def main() -> int:
    vendor_configs = discover_vendor_configs()
    if not vendor_configs:
        logger.error(
            "V %s nejsou zadne *.yaml soubory - neni koho kontrolovat.", DEVICES_DIR
        )
        return 1

    all_updates: list[Update] = []

    for vendor, cfg in vendor_configs.items():
        logger.info("=== %s ===", vendor.upper())
        scrape_fn = load_scraper(vendor)
        if scrape_fn is None:
            continue
        try:
            all_updates.extend(scrape_fn(cfg))
        except Exception as exc:  # noqa: BLE001 - jeden vyrobce nesmi shodit cely beh
            logger.exception("%s scraper spadl: %s", vendor, exc)

    before_filter = len(all_updates)
    all_updates = [u for u in all_updates if is_relevant_update(u)]
    logger.info(
        "Filtr firmware/security: ponechano %d z %d zaznamu (vyrazeny obecne OS ovladace bez "
        "bezpecnostni relevance).",
        len(all_updates), before_filter,
    )

    now_iso = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    latest_records = [u.to_dict() for u in all_updates]

    # historie: pro kazdy zaznam (podle key) si pamatujeme, kdy byl poprve
    # a naposledy videny - umoznuje to na webu oznacit "nove od posledni kontroly".
    history = load_json(HISTORY_PATH, {})
    new_keys = []
    for rec in latest_records:
        k = rec["key"]
        if k not in history:
            history[k] = {"first_seen": now_iso, **rec}
            new_keys.append(k)
        history[k]["last_seen"] = now_iso

    save_json(LATEST_PATH, {"generated_at": now_iso, "count": len(latest_records), "updates": latest_records})
    save_json(HISTORY_PATH, history)

    logger.info(
        "Hotovo: %d aktualnich zaznamu celkem, %d novych od posledniho behu.",
        len(latest_records),
        len(new_keys),
    )
    if new_keys:
        for k in new_keys:
            r = history[k]
            logger.info("  NOVE: [%s] %s %s %s - %s (%s)", r["vendor"], r["family"], r["generation"], r["update_id"], r["release_date"], r["description"][:80])

    return 0


if __name__ == "__main__":
    sys.exit(main())
