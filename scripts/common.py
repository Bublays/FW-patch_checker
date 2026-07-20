"""Sdílené datové struktury a pomocné funkce pro všechny scrapery."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
from datetime import datetime, date
from typing import Optional

import requests

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

USER_AGENT = "fw-checker/1.0 (+https://github.com/; kontrola dostupnych firmware/patch aktualizaci)"

DEFAULT_HEADERS = {"User-Agent": USER_AGENT}

REQUEST_TIMEOUT = 60


@dataclasses.dataclass
class Update:
    vendor: str            # HPE / Dell / IBM
    family: str            # napr. "DL380", "PowerEdge R740", "FS7300"
    generation: str        # napr. "Gen11", "" (pokud se nehodi)
    update_id: str         # cislo/verze update (napr. "U54 v2.60", "1.5.0.2-C00")
    release_date: str      # ISO 8601 "YYYY-MM-DD", nebo "" pokud neznamo
    description: str       # kratky popis
    category: str = ""     # BIOS / Firmware - Storage / Driver / ...
    source_url: str = ""   # odkaz na zdroj / stazeni

    def key(self) -> str:
        """Stabilni klic pro deduplikaci a detekci "co je nove"."""
        raw = "|".join([self.vendor, self.family, self.generation, self.update_id])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["key"] = self.key()
        return d


def get(url: str, **kwargs) -> requests.Response:
    """requests.get s rozumnym default timeoutem, hlavickou a retry na 1 pokus navic."""
    headers = {**DEFAULT_HEADERS, **kwargs.pop("headers", {})}
    last_exc: Optional[Exception] = None
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001 - chceme zalogovat a zkusit znovu
            last_exc = exc
            logging.getLogger("common").warning("GET %s selhal (pokus %d): %s", url, attempt + 1, exc)
    assert last_exc is not None
    raise last_exc


def parse_date_loose(value: str) -> str:
    """Zkusi rozparsovat datum v ruznych formatech na ISO 8601. Pri neuspechu vrati puvodni string."""
    if not value:
        return ""
    value = value.strip()
    fmts = [
        "%Y-%m-%d",
        "%m/%d/%y",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%B %Y",
        "%b %Y",
        "%d %B %Y",
        "%B %d, %Y",
        "%Y%m%d",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(value, fmt)
            if fmt == "%B %Y" or fmt == "%b %Y":
                return date(dt.year, dt.month, 1).isoformat()
            return dt.date().isoformat()
        except ValueError:
            continue
    return value


def save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
