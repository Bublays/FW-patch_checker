"""
Offline validace parsovaci logiky proti realnym / realistickym vzorkum dat,
bez pristupu k internetu (sandbox, ve kterem tento kod vznikl, nema pristup
k domenam vyrobcu - plny end-to-end test tedy probehne az v GitHub Actions).

Overuje:
  - scrape_hpe: parsovani meta.xml / system.xml a spravne rozliseni
    Gen10 vs. Gen10 Plus podle nazvu systemu
  - scrape_ibm: regex na "Firmware Level / Release Date" bloky z realneho
    formatu TS4300_fixlist.txt (vzorek stazeny primo z delivery04.dhe.ibm.com)
  - scrape_dell: parsovani SoftwareComponent schematu z Dell katalogu
  - common.parse_date_loose: prevod ruznych formatu data na ISO 8601
"""
import os
import sys
from unittest.mock import patch
from xml.etree import ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)

import common  # noqa: E402
import scrape_hpe  # noqa: E402
import scrape_ibm  # noqa: E402
import scrape_dell  # noqa: E402


class FakeResponse:
    def __init__(self, text=None, content=None):
        self.text = text if text is not None else (content.decode("utf-8") if content else "")
        self.content = content if content is not None else (text.encode("utf-8") if text else b"")

    def raise_for_status(self):
        pass


def test_hpe_gen_matching():
    print("== HPE: rozliseni Gen10 vs Gen10 Plus ==")
    assert scrape_hpe._system_matches("HPE ProLiant DL380 Gen10 Server", "DL380", "Gen10") is True
    assert scrape_hpe._system_matches("HPE ProLiant DL380 Gen10 Plus Server", "DL380", "Gen10") is False
    assert scrape_hpe._system_matches("HPE ProLiant DL380 Gen10 Plus Server", "DL380", "Gen10 Plus") is True
    assert scrape_hpe._system_matches("HPE ProLiant DL380 Gen11 Server", "DL380", "Gen11") is True
    assert scrape_hpe._system_matches("HPE ProLiant DL325 Gen11 Server", "DL380", "Gen11") is False
    print("  OK")


def test_hpe_end_to_end():
    print("== HPE: end-to-end scrape() na vzorovych XML datech ==")
    fixture_dir = HERE
    meta_path = os.path.join(fixture_dir, "hpe_meta_sample.xml")
    system_path = os.path.join(fixture_dir, "hpe_system_sample.xml")

    def fake_get(url, **kwargs):
        if url.endswith("spp-gen11/") or url.endswith("spp-gen10/"):
            return FakeResponse(text='<a href="2026.05.00.00/">2026.05.00.00/</a>')
        if "meta.xml" in url:
            with open(meta_path, "rb") as f:
                return FakeResponse(content=f.read())
        if "system.xml" in url:
            with open(system_path, "rb") as f:
                return FakeResponse(content=f.read())
        raise AssertionError(f"neocekavana URL {url}")

    with patch.object(scrape_hpe, "get", fake_get):
        updates = scrape_hpe.scrape(["DL380"], ["Gen11", "Gen10 Plus"])

    families_gens = {(u.family, u.generation, u.update_id) for u in updates}
    print("  nalezeno:", families_gens)
    assert ("DL380", "Gen11", "U54(v2.60)") in families_gens
    assert ("DL380", "Gen11", "2.90") in families_gens
    assert ("DL380", "Gen10 Plus", "2.90") in families_gens
    assert all(u.generation != "Gen10 Plus" or u.update_id != "U54(v2.60)" for u in updates), (
        "System ROM pro Gen11 by se nemel priradit ke Gen10 Plus"
    )
    print("  OK -", len(updates), "zaznamu, spravne rozliseno podle generace")


def test_ibm_tape_fixlist_parsing():
    print("== IBM: parsovani TS4300_fixlist.txt (realny format) ==")
    sample_path = os.path.join(HERE, "ts4300_sample.txt")
    with open(sample_path, "r", encoding="utf-8") as f:
        text = f.read()
    matches = list(scrape_ibm._FW_BLOCK_RE.finditer(text))
    assert len(matches) == 2, f"Ocekavany 2 bloky firmware, nalezeno {len(matches)}"
    levels = [m.group("level").strip() for m in matches]
    dates = [m.group("date").strip() for m in matches]
    assert levels == ["1.5.0.2-C00", "1.4.1.0-B00"]
    assert dates == ["11/30/22", "05/31/21"]
    assert common.parse_date_loose(dates[0]) == "2022-11-30"
    print("  OK - nalezeny verze:", levels, "-> data:", [common.parse_date_loose(d) for d in dates])


def test_parse_date_loose():
    print("== common.parse_date_loose ==")
    assert common.parse_date_loose("05/31/21") == "2021-05-31"
    assert common.parse_date_loose("July 2026") == "2026-07-01"
    assert common.parse_date_loose("2026-07-17") == "2026-07-17"
    assert common.parse_date_loose("") == ""
    print("  OK")


def test_dell_catalog_parsing():
    print("== Dell: parsovani katalogoveho XML (SoftwareComponent schema) ==")
    sample_path = os.path.join(HERE, "dell_catalog_sample.xml")
    tree = ET.parse(sample_path)
    root = tree.getroot()

    with patch.object(scrape_dell, "_download_catalog", lambda: root):
        updates = scrape_dell.scrape(["PowerEdge R440", "PowerEdge R740", "PowerEdge T140"])

    families = {u.family for u in updates}
    print("  nalezeno modelu:", families)
    assert families == {"PowerEdge R740", "PowerEdge R440"}, families
    r740 = next(u for u in updates if u.family == "PowerEdge R740")
    assert r740.update_id == "2.19.2"
    assert r740.release_date == "2026-04-15"
    assert r740.source_url == "https://www.dell.com/support/kbdoc/000123456"
    assert all(u.family != "PowerEdge R6515" for u in updates)
    print("  OK -", len(updates), "zaznamu, nerelevantni model spravne vyfiltrovan")


if __name__ == "__main__":
    test_parse_date_loose()
    test_hpe_gen_matching()
    test_hpe_end_to_end()
    test_ibm_tape_fixlist_parsing()
    test_dell_catalog_parsing()
    print("\nVSECHNY OFFLINE TESTY PROSLY")
