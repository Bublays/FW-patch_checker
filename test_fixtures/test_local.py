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
import run_all  # noqa: E402


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
        updates = scrape_hpe.scrape({"families": ["DL380"], "generations": ["Gen11", "Gen10 Plus"]})

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
        updates = scrape_dell.scrape({"models": ["PowerEdge R440", "PowerEdge R740", "PowerEdge T140"]})

    families = {u.family for u in updates}
    print("  nalezeno modelu:", families)
    assert families == {"PowerEdge R740", "PowerEdge R440"}, families
    r740 = next(u for u in updates if u.family == "PowerEdge R740")
    assert r740.update_id == "2.19.2"
    assert r740.release_date == "2026-04-15"
    assert r740.source_url == "https://www.dell.com/support/kbdoc/000123456"
    assert all(u.family != "PowerEdge R6515" for u in updates)
    print("  OK -", len(updates), "zaznamu, nerelevantni model spravne vyfiltrovan")


def test_ibm_flashsystem_split_strong_tags():
    print("== IBM: FlashSystem regex toleruje rozdelene <strong> tagy ==")
    sample_path = os.path.join(HERE, "ibm_flashsystem_split_tags_sample.html")

    def fake_get(url, **kwargs):
        with open(sample_path, "r", encoding="utf-8") as f:
            return FakeResponse(text=f.read())

    with patch.object(scrape_ibm, "get", fake_get):
        updates = scrape_ibm._scrape_flashsystem("FS5300", "IBM FlashSystem 5300", "https://example.com/5000-family")

    ids_dates = {(u.update_id, u.release_date) for u in updates}
    print("  nalezeno:", ids_dates)
    assert ("9.1.3.0", "2026-07-01") in ids_dates
    assert ("9.1.0.3", "2026-01-01") in ids_dates
    assert ("9.1.2.0", "2026-03-01") in ids_dates
    print("  OK -", len(updates), "zaznamu i pres rozdelene HTML tagy")


def test_ibm_tape_fixlist_direct_txt():
    print("== IBM: primy fixlist.txt (TS4300) pres novou funkci ==")
    sample_path = os.path.join(HERE, "ts4300_sample.txt")

    def fake_get(url, **kwargs):
        assert "fixlist" in url
        with open(sample_path, "r", encoding="utf-8") as f:
            return FakeResponse(text=f.read())

    cfg = {
        "fixlist_txt_url": "https://example.com/TS4300_fixlist.txt",
        "fix_readme_page": "https://example.com/ts4300-fix-readme",
    }
    with patch.object(scrape_ibm, "get", fake_get):
        updates = scrape_ibm._scrape_tape_fixlist("TS4300", "IBM TS4300 Tape Library", cfg)

    levels = {u.update_id for u in updates}
    assert levels == {"1.5.0.2-C00", "1.4.1.0-B00"}
    print("  OK -", len(updates), "zaznamu primo z .txt souboru")


def test_ibm_diamondback_recommendation_table():
    print("== IBM: tabulka Code Update Recommendation (Diamondback) ==")
    sample_path = os.path.join(HERE, "ibm_diamondback_recommendation_sample.html")

    def fake_get(url, **kwargs):
        with open(sample_path, "r", encoding="utf-8") as f:
            return FakeResponse(text=f.read())

    with patch.object(scrape_ibm, "get", fake_get):
        updates = scrape_ibm._scrape_recommendation_table(
            "Diamondback", "IBM Diamondback Tape Library", "https://example.com/diamondback-recommendation"
        )

    versions = {u.update_id for u in updates}
    print("  nalezeno verzi:", versions)
    assert "2.11.0.4-C00" in versions, "verze rozdelena <a> tagem se musi spravne slozit dohromady"
    assert "2.11.0.5-A00" in versions
    assert "2.12.0.2-C00" in versions
    assert "LTOA_S57A" in versions
    latest_row = next(u for u in updates if u.update_id == "2.12.0.2-C00")
    assert latest_row.release_date == "2026-03-01"
    assert "Latest Level" in latest_row.description
    print("  OK -", len(updates), "zaznamu z tabulky (vcetne verze rozdelene odkazem)")


def test_ibm_ts4300_recommendation_table():
    print("== IBM: tabulka Code Update Recommendation (TS4300) ==")
    sample_path = os.path.join(HERE, "ibm_ts4300_recommendation_sample.html")

    def fake_get(url, **kwargs):
        with open(sample_path, "r", encoding="utf-8") as f:
            return FakeResponse(text=f.read())

    with patch.object(scrape_ibm, "get", fake_get):
        updates = scrape_ibm._scrape_recommendation_table(
            "TS4300", "IBM TS4300 Tape Library", "https://example.com/ts4300-recommendation"
        )

    versions = {u.update_id for u in updates}
    print("  nalezeno verzi:", versions)
    assert "1.7.2.0-C00" in versions, "verze rozdelena na 7 <a> fragmentu se musi spravne slozit dohromady"
    assert "1.7.1.1-A00" in versions
    assert "1.6.0.0-A00" in versions
    latest_5544 = next(u for u in updates if u.update_id == "1.7.2.0-C00" and "5544" in u.family)
    assert latest_5544.release_date == "2026-04-01"
    print("  OK -", len(updates), "zaznamu, nejnovejsi verze (Apr 2026) spravne zachycena")


def test_run_all_auto_discovery():
    print("== run_all: auto-discovery vyrobcu z config/devices/*.yaml ==")
    configs = run_all.discover_vendor_configs()
    print("  nalezene config soubory:", sorted(configs.keys()))
    assert {"hpe", "dell", "ibm"} <= set(configs.keys()), (
        "ocekavany minimalne hpe/dell/ibm config soubory v config/devices/"
    )
    assert "families" in configs["hpe"] and "generations" in configs["hpe"]
    assert "models" in configs["dell"]
    assert "flashsystem" in configs["ibm"]

    for vendor in ("hpe", "dell", "ibm"):
        scrape_fn = run_all.load_scraper(vendor)
        assert scrape_fn is not None, f"scrape_{vendor}.py by mel byt dohledatelny a mit funkci scrape(cfg)"
        assert callable(scrape_fn)

    assert run_all.load_scraper("neexistujici_vyrobce") is None
    print("  OK - vsichni 3 vyrobci nalezeni a spareni s odpovidajicim scrape_<vyrobce>.py")


if __name__ == "__main__":
    test_parse_date_loose()
    test_hpe_gen_matching()
    test_hpe_end_to_end()
    test_ibm_tape_fixlist_parsing()
    test_dell_catalog_parsing()
    test_ibm_flashsystem_split_strong_tags()
    test_ibm_tape_fixlist_direct_txt()
    test_ibm_diamondback_recommendation_table()
    test_ibm_ts4300_recommendation_table()
    test_run_all_auto_discovery()
    print("\nVSECHNY OFFLINE TESTY PROSLY")
