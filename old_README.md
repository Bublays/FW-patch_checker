# FW checker

Automaticky sleduje dostupné firmware update a patche pro vybraná zařízení
HPE, Dell a IBM. Jednou týdně (nebo na vyžádání) stáhne aktuální data
z veřejných portálů výrobců, uloží je do repozitáře a publikuje jako
přehlednou tabulku na GitHub Pages.

**Žádné přihlašovací údaje nejsou potřeba** — všechny tři scrapery používají
veřejné, nezaheslované zdroje (viz níže).

## Rychlý start

1. Založ nový GitHub repozitář a nahraj do něj obsah této složky.
2. V nastavení repozitáře: **Settings → Pages → Source: GitHub Actions**.
3. V nastavení repozitáře: **Settings → Actions → General → Workflow permissions**
   nastav na *"Read and write permissions"* (aby workflow mohl commitovat
   aktualizovaná data zpátky do repozitáře).
4. Spusť workflow ručně: záložka **Actions → Firmware & patch check → Run workflow**,
   nebo počkej na první naplánovaný běh (pondělí 6:00 UTC).
5. Po doběhnutí najdeš stránku na `https://<tvůj-účet>.github.io/<repo>/`.

## Jak to funguje

```
config/devices.yaml     — seznam sledovaných zařízení (uprav podle potřeby)
scripts/scrape_dell.py  — Dell scraper
scripts/scrape_hpe.py   — HPE scraper
scripts/scrape_ibm.py   — IBM scraper
scripts/run_all.py      — spustí všechny scrapery, uloží data/latest.json a data/history.json
scripts/build_site.py   — z data/latest.json vygeneruje statickou stránku do docs/
.github/workflows/      — plánovaná úloha (cron) + deploy na GitHub Pages
```

Výstup (`data/latest.json`, i zobrazený na stránce) obsahuje pro každý update:
výrobce, zařízení, generaci, **číslo update/verzi**, **datum vydání** a
**krátký popis**, plus odkaz na zdroj.

`data/history.json` si pamatuje, kdy byl který update poprvé zaznamenán —
nově objevené položky jsou na stránce zvýrazněné.

## Zdroje dat (bez přihlášení)

| Výrobce | Zdroj | Poznámka |
|---|---|---|
| **Dell** | `downloads.dell.com/catalog/Catalog.xml.gz` — veřejný katalog používaný Dell Repository Manager / OpenManage / Dell Command Update | Obsahuje BIOS, firmware i ovladače pro všechny PowerEdge modely; filtrujeme podle `SupportedSystems/Model`. Katalog je velký (desítky až stovky MB), stažení chvíli trvá. |
| **HPE** | `downloads.linux.hpe.com/SDR/repo/spp-<generace>/` — veřejné HPE Software Delivery Repository (stejná data jako Service Pack for ProLiant / Smart Update Manager) | Pro každou generaci (Gen10/Gen10 Plus/Gen11/Gen12) se stáhne nejnovější sada `system.xml` (mapování model → komponenty) a `meta.xml` (verze/datum/popis komponent). |
| **IBM FlashSystem** (7300/5300/5200) | `ibm.com/support/pages/support-information-flashsystem-*-family` | Veřejná stránka se seznamem vydaných verzí IBM Storage Virtualize a daty vydání. |
| **IBM tape** (TS4300, Diamondback) | `ibm.com/support/pages/<model>-fix-readme` → odkaz na `<model>_fixlist.txt` na `delivery04.dhe.ibm.com` | Strukturovaný textový seznam firmware verzí s daty a popisem změn. |

## Známá omezení / co si pohlídat

- **IBM Diamondback**: URL fix-readme stránky v `config/devices.yaml`
  (`diamondback-tape-library-fix-readme`) je odhad podle vzoru ostatních IBM
  tape produktů (TS4300, TS4500, TS2900) — v době přípravy nebylo možné
  ověřit, že přesně existuje. Pokud scraper po prvním běhu nic nenajde,
  zkontroluj na [ibm.com/support](https://www.ibm.com/support) skutečnou
  URL a uprav ji v configu.
- **HPE Gen10 vs. Gen10 Plus**: obě generace sdílí stejnou větev repozitáře
  (`spp-gen10`), rozlišují se podle názvu systému v `system.xml`. Pokud HPE
  název formátu změní, může být potřeba upravit `_system_matches()` v
  `scripts/scrape_hpe.py`.
- **Dell katalog je rozsáhlý** — první běh v GitHub Actions může trvat
  několik minut jen na stažení a rozparsování.
- Weby výrobců čas od času mění strukturu/URL. Každý scraper loguje chyby
  jednotlivě a nespadne celý běh kvůli jednomu výrobci — zkontroluj vždy log
  běhu (**Actions → poslední běh**), pokud se ti zdá, že pro nějaké
  zařízení chybí data.

## Úprava seznamu zařízení

Otevři `config/devices.yaml` a přidej/uber modely nebo generace. Kód se
měnit nemusí — filtrování probíhá dynamicky podle configu.

## Lokální spuštění (bez GitHubu)

```bash
pip install -r requirements.txt
cd scripts
python run_all.py       # stáhne data do ../data/latest.json
python build_site.py    # vygeneruje ../docs/index.html
```
