# DVK Election Exporter (Slovenia, DZ 2026)

Python app for live election-night exports from DVK, with:

- exact-template exports for OBS/Expression (`stoli.csv`, `udelezba.csv`)
- modern GUI (Streamlit)
- automation (continuous no-click updates)
- source transparency (exact URLs + source used per export)
- custom export builder (pick fields, output CSV/JSON)

---

## Features

- **Election overlay exports**
  - `stoli.csv` in your exact row/column structure
  - `udelezba.csv` in your exact row/column structure
- **User-friendly GUI**
  - one-click export
  - start/stop automation loop
  - live file preview
- **Data-source transparency**
  - shows exact DVK endpoints used
  - writes `export_status.json` with `source_used` and field status
- **Custom export builder**
  - browse available DVK fields
  - choose fields + style
  - export as CSV or JSON

---

## Data Sources and Priority

Based on DVK DZ 2026 data-file documentation, export logic uses this strict priority:

1. `rezultati.json` + `udelezba.json` (**preferred official election-day source**)
2. `rezultati.csv` + `udelezba.csv` (official fallback)
3. `data.json` + `liste.json` (legacy app fallback)

### Endpoints (default election: `dz2026`)

- `https://volitve.dvk-rs.si/dz2026/data/udelezba.json`
- `https://volitve.dvk-rs.si/dz2026/data/rezultati.json`
- `https://volitve.dvk-rs.si/dz2026/data/kandidati_rezultat.json`
- `https://volitve.dvk-rs.si/dz2026/data/udelezba.csv`
- `https://volitve.dvk-rs.si/dz2026/data/rezultati.csv`
- `https://volitve.dvk-rs.si/dz2026/data/mandati.csv`

---

## Requirements

- Python 3.10+
- Internet access to DVK

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Quick Start (GUI)

### Option A (recommended)

```bash
python -m streamlit run dvk_gui.py
```

### Option B (Windows double-click)

Use:

```text
start_gui.bat
```

Then open the Streamlit URL (usually `http://localhost:8501`).

---

## GUI Workflow

1. Open sidebar settings and configure:
   - election slug (default `dz2026`)
   - output directory
   - template file paths (`stoli.csv`, `udelezba.csv`)
   - automation interval
2. Click **Save settings**.
3. Use:
   - **Export now**
   - **Export now + raw JSON**
4. For no-click updates:
   - click **Start automation**
   - keep app open
   - click **Stop automation** when done

---

## CLI Usage

One-time export:

```bash
python dvk_exporter.py export
```

One-time export + raw DVK bundle:

```bash
python dvk_exporter.py export --dump-raw
```

Continuous automation:

```bash
python dvk_exporter.py watch
```

Terminal interactive mode:

```bash
python dvk_exporter.py interactive
```

---

## Output Files

- `stoli.csv` — seats and percentages by party (template-preserving)
- `udelezba.csv` — turnout and counted votes (template-preserving)
- `export_status.json` — export diagnostics:
  - fetched timestamp
  - exact source endpoints
  - source actually used (`source_used`)
  - per-party `official/missing` field status
- `dvk_raw_YYYYMMDD_HHMMSS.json` — optional raw bundle snapshot (`--dump-raw`)

---

## Accuracy Notes

- Percent values in DVK JSON are decimals (e.g. `0.4825`); app converts to display percent (`48.3` style in CSV output).
- Counted-votes percent follows documented formula:
  - `rezultati.glas / udelezba.slovenija.gl`
- If a value is not yet published by DVK, output remains blank instead of inventing numbers.
- Mandates/seats are sourced from official fields (including `man` and mandate variants).

---

## Election-Day Checklist

1. Start GUI before live coverage.
2. Confirm **Data sources** panel shows expected DZ 2026 endpoints.
3. Run **Export now** once.
4. Check `export_status.json`:
   - `source_used.results` should be `rezultati.json` when available.
   - seats/percent statuses should move from `missing` to `official`.
5. Start automation and keep GUI open.
6. Point OBS/Expression to `stoli.csv` and `udelezba.csv`.

---

## Project Files

- `dvk_exporter.py` — core fetching, mapping, exporting
- `dvk_gui.py` — Streamlit GUI
- `settings.json` — persisted settings
- `requirements.txt` — dependencies
- `start_gui.bat` — Windows launcher

