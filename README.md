# FW checker

Automaticky sleduje dostupné firmware update a patche pro vybraná zařízení
HPE, Dell, IBM a VMware. Jednou týdně (nebo na vyžádání) stáhne aktuální data
z veřejných portálů výrobců, uloží je do repozitáře a publikuje jako
přehlednou tabulku na GitHub Pages.

**Žádné přihlašovací údaje nejsou potřeba** — všechny scrapery používají
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
config/devices/hpe.yaml    — seznam sledovaných HPE zařízení
config/devices/dell.yaml   — seznam sledovaných Dell zařízení
config/devices/ibm.yaml    — seznam sledovaných IBM zařízení
config/devices/vmware.yaml — seznam sledovaných VMware produktů/verzí
scripts/scrape_dell.py  — Dell scraper
scripts/scrape_hpe.py   — HPE scraper
scripts/scrape_ibm.py   — IBM scraper
scripts/scrape_vmware.py — VMware/Broadcom scraper
scripts/run_all.py      — najde config/devices/*.yaml, spustí odpovídající scrapery,
                           uloží data/latest.json a data/history.json
scripts/build_site.py   — z data/latest.json vygeneruje statickou stránku do docs/
.github/workflows/      — plánovaná úloha (cron) + deploy na GitHub Pages
```

`run_all.py` si výrobce sám najde podle konvence: pro každý
`config/devices/<vyrobce>.yaml` očekává modul `scripts/scrape_<vyrobce>.py`
s funkcí `scrape(cfg)`, kde `cfg` je celý obsah daného YAML souboru. Díky
tomu se `run_all.py` nemusí upravovat, ani kdyby přibyl další výrobce se
stejným typem zdroje.

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
| **IBM TS4300** | `ibm.com/support/pages/ts4300-fix-readme` (bohatá historie s popisem změn) **+** `ibm.com/support/pages/ibm-ts4300-code-update-recommendation` (tabulka Minimum/Recommended/Latest Level) | Kombinace dvou zdrojů — viz níže "Proč dva zdroje pro TS4300". |
| **IBM Diamondback** | `ibm.com/support/pages/ibm-diamondback-code-update-recommendation` | Diamondback nemá samostatnou historii jako TS4300 — IBM zveřejňuje jen tabulku Minimum/Recommended/Latest Level s daty; parsujeme přímo tuto tabulku. |
| **VMware ESXi** | `knowledge.broadcom.com/external/article/316595` — veřejný KB článek "Build numbers and versions of VMware ESXi/ESX" | Stránka má samostatnou tabulku pro každou major verzi (historie sahá do ~2007) — parsujeme jen tabulky pod nadpisy uvedenými v `versions` u daného produktu v configu. |
| **VMware vCenter Server** | `knowledge.broadcom.com/external/article/326316` — veřejný KB článek "VMware vCenter Server versions and build numbers" | Stejný princip jako u ESXi. Sloupce se mezi tabulkami mírně liší (např. novější verze nemají samostatný sloupec "Release name") — scraper sloupce mapuje podle textu hlavičky, ne podle pevné pozice. |

### Proč dva zdroje pro TS4300

Původně jsme používali přímý odkaz na `TS4300_fixlist.txt` na
`delivery04.dhe.ibm.com/.../<hash>/...` jako primární zdroj. Ukázalo se ale,
že IBM při každém novém vydání generuje v cestě NOVÝ hash — jakýkoli jednou
zapsaný přímý odkaz tak časem zůstane navždy ukazovat na starou verzi (takhle
jsme nepozorovaně zůstali na verzi z roku 2021). Tenhle přímý odkaz jsme
proto z configu odstranili.

Zkoušeli jsme i oficiální IBM Fix Central (`ibm.com/support/fixcentral/...`),
odkud si uživatelé firmware stahují ručně — to je ale JavaScriptová aplikace
se session/pollingem ("Please wait, identifying fixes…"), kterou nejde
jednoduchým HTTP requestem přečíst; vyžadovala by headless prohlížeč
(Playwright/Selenium) v GitHub Actions, což je výrazně křehčí a pomalejší
řešení pro starou JSP aplikaci, která se navíc může kdykoliv změnit.

Místo toho používáme dvě statické, snadno parsovatelné stránky:
- **`ts4300-fix-readme`** — obsahuje kompletní historii verzí i s popisem
  oprav, ale ne vždy je 100% aktuální (viděli jsme zpoždění cca 6 měsíců
  oproti Fix Central).
- **`ibm-ts4300-code-update-recommendation`** — stejný formát tabulky, jaký
  už používáme pro Diamondback (Minimum/Recommended/Latest Level), a která
  spolehlivě ukazuje opravdu nejnovější vydanou verzi.

Tím získáme bohatou historii i jistotu, že nám neunikne nejnovější verze,
bez nutnosti řešit JS/session automatizaci.

## Známá omezení / co si pohlídat

- **HPE Gen10 vs. Gen10 Plus**: obě generace sdílí stejnou větev repozitáře
  (`spp-gen10`), rozlišují se podle názvu systému v `system.xml`. Pokud HPE
  název formátu změní, může být potřeba upravit `_system_matches()` v
  `scripts/scrape_hpe.py`.
- **Dell katalog je rozsáhlý** — první běh v GitHub Actions může trvat
  několik minut jen na stažení a rozparsování.
- **Pokud HPE vrátí 0 záznamů**: scraper teď loguje diagnostiku — kolik
  systémů/komponent se z manifestu načetlo a (pokud se pro danou rodinu/
  generaci nic nenašlo) ukázku skutečných názvů systémů v repozitáři. Podívej
  se do logu kroku "Run scrapers" a porovnej ukázkové názvy s tím, co
  `_system_matches()` v `scripts/scrape_hpe.py` očekává.
- Weby výrobců čas od času mění strukturu/URL. Každý scraper loguje chyby
  jednotlivě a nespadne celý běh kvůli jednomu výrobci — zkontroluj vždy log
  běhu (**Actions → poslední běh**), pokud se ti zdá, že pro nějaké
  zařízení chybí data.
- **VMware stránky mají historii od ~2007** — zpracovávají se jen tabulky
  pod nadpisy uvedenými v `versions` (viz `config/devices/vmware.yaml`). Až
  vyjde nová major verze (např. ESXi 10.0), přidej ji do `versions` u
  daného produktu, jinak se v přehledu neobjeví.

## Úprava seznamu zařízení

Otevři příslušný soubor v `config/devices/` (`hpe.yaml` / `dell.yaml` /
`ibm.yaml` / `vmware.yaml`) a přidej/uber modely, generace nebo verze. Kód
se měnit nemusí — filtrování probíhá dynamicky podle configu.

## Přidání nového výrobce (např. Lenovo, Fortinet)

Protože každý výrobce publikuje aktualizace jinak (jiný formát stránky/API),
nejde postavit jeden univerzální scraper pro všechny — nový výrobce si vždy
vyžádá vlastní malý parser. Rozsah zásahu je ale omezený jen na tyto dva
nové soubory, nikde jinde se nic upravovat nemusí:

1. **`config/devices/<vyrobce>.yaml`** — seznam sledovaných zařízení (libovolná
   struktura, podle toho, co scraper potřebuje).
2. **`scripts/scrape_<vyrobce>.py`** — modul s veřejnou funkcí
   `scrape(cfg) -> list[Update]`, kde `cfg` je obsah souboru z bodu 1.
   `Update` je dataclass z `scripts/common.py` (vendor, family, generation,
   update_id, release_date, description, category, source_url).

Název YAML souboru a název výrobce v modulu (za `scrape_`) musí být stejný
— `run_all.py` je podle toho spáruje automaticky, žádná registrace navíc
není potřeba.

Pokud chceš pro nového výrobce i vlastní barvu badge/karty na stránce,
přidej mu v `scripts/build_site.py` obdobu `--hpe`/`--dell`/`--ibm`
proměnných a CSS třídy `.badge.<Vyrobce>` / `.card.<vyrobce>`.

## Lokální spuštění (bez GitHubu)

```bash
pip install -r requirements.txt
cd scripts
python run_all.py       # stáhne data do ../data/latest.json
python build_site.py    # vygeneruje ../docs/index.html
```
