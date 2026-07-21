"""
Hlavni orchestracni skript. Nacte config/devices.yaml, spusti scrapery pro
vsechny 3 vyrobce, ulozi vysledek do data/latest.json a udrzuje
data/history.json (kvuli detekci "co je od posledni kontroly nove").

Pouziti:
    python scripts/run_all.py

Vystupni kody:
    0 - probehlo v poradku (i kdyz nektery vyrobce selhal - viz log)
    1 - fatalni chyba (spatny config apod.)
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(__file__))

from common import Update, save_json, load_json  # noqa: E402
import scrape_dell  # noqa: E402
import scrape_hpe  # noqa: E402
import scrape_ibm  # noqa: E402

logger = logging.getLogger("run_all")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "devices.yaml")
DATA_DIR = os.path.join(ROOT, "data")
LATEST_PATH = os.path.join(DATA_DIR, "latest.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> int:
    cfg = load_config()
    all_updates: list[Update] = []

    logger.info("=== Dell ===")
    try:
        all_updates.extend(scrape_dell.scrape(cfg["dell"]["models"]))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Dell scraper spadl: %s", exc)

    logger.info("=== HPE ===")
    try:
        all_updates.extend(
            scrape_hpe.scrape(cfg["hpe"]["families"], cfg["hpe"]["generations"])
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("HPE scraper spadl: %s", exc)

    logger.info("=== IBM ===")
    try:
        all_updates.extend(
            scrape_ibm.scrape(
                cfg["ibm"]["flashsystem"],
                cfg["ibm"]["tape_fixlist"],
                cfg["ibm"]["tape_recommendation"],
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("IBM scraper spadl: %s", exc)

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
