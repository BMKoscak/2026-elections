from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


SETTINGS_FILE = "settings.json"
DEFAULT_ELECTION = "dz2026"
DEFAULT_BASE_URL = "https://volitve.dvk-rs.si"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def norm_key(s: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(s))
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_only.lower())


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        v = value.strip().replace(",", ".")
        if not v:
            return None
        try:
            return float(v)
        except ValueError:
            return None
    return None


def to_int(value: Any) -> int | None:
    f = to_float(value)
    if f is None:
        return None
    return int(round(f))


def load_json_url(url: str, timeout: int = 20) -> Any:
    with urlopen(url, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def load_text_url(url: str, timeout: int = 20) -> str:
    with urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def try_load_json_url(url: str, timeout: int = 20) -> Any | None:
    try:
        return load_json_url(url, timeout=timeout)
    except Exception:
        return None


def try_load_text_url(url: str, timeout: int = 20) -> str | None:
    try:
        return load_text_url(url, timeout=timeout)
    except Exception:
        return None


def deep_find_numeric(node: Any, keys: list[str], int_like: bool = False) -> float | int | None:
    keyset = {norm_key(k) for k in keys}
    if isinstance(node, dict):
        for k, v in node.items():
            nk = norm_key(k)
            if nk in keyset or any(t in nk or nk in t for t in keyset):
                if int_like:
                    found = to_int(v)
                else:
                    found = to_float(v)
                if found is not None:
                    return found
        for v in node.values():
            found = deep_find_numeric(v, keys, int_like=int_like)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = deep_find_numeric(item, keys, int_like=int_like)
            if found is not None:
                return found
    return None


@dataclass
class Settings:
    election: str = DEFAULT_ELECTION
    base_url: str = DEFAULT_BASE_URL
    interval_seconds: int = 30
    output_dir: str = "."
    stoli_template: str = "stoli.csv"
    udelezba_template: str = "udelezba.csv"

    @staticmethod
    def from_file(path: Path) -> "Settings":
        if not path.exists():
            return Settings()
        data = json.loads(path.read_text(encoding="utf-8"))
        return Settings(
            election=data.get("election", DEFAULT_ELECTION),
            base_url=data.get("base_url", DEFAULT_BASE_URL),
            interval_seconds=int(data.get("interval_seconds", 30)),
            output_dir=data.get("output_dir", "."),
            stoli_template=data.get("stoli_template", "stoli.csv"),
            udelezba_template=data.get("udelezba_template", "udelezba.csv"),
        )

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(self.__dict__, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class DVKClient:
    def __init__(self, base_url: str, election: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.election = election.strip("/")

    def _url(self, rel: str) -> str:
        return f"{self.base_url}/{self.election}/{rel.lstrip('/')}"

    def endpoint_map(self) -> dict[str, str]:
        cfg_url = self._url("config/config.json")
        cfg = load_json_url(cfg_url)
        prefix = cfg.get("dataUrlPrefix", "data/")
        data_file = cfg.get("dataFile", "data.json")
        liste_file = cfg.get("listeFile", "liste.json")
        kandidati_file = cfg.get("vsiKandidatiFile", "kandidati.json")
        return {
            "config_url": cfg_url,
            "data_url": self._url(f"{prefix}{data_file}"),
            "liste_url": self._url(f"{prefix}{liste_file}"),
            "kandidati_url": self._url(f"{prefix}{kandidati_file}"),
            "udelezba_json_url": self._url(f"{prefix}udelezba.json"),
            "rezultati_json_url": self._url(f"{prefix}rezultati.json"),
            "kandidati_rezultat_json_url": self._url(f"{prefix}kandidati_rezultat.json"),
            "udelezba_csv_url": self._url(f"{prefix}udelezba.csv"),
            "rezultati_csv_url": self._url(f"{prefix}rezultati.csv"),
            "mandati_csv_url": self._url(f"{prefix}mandati.csv"),
        }

    def fetch_bundle(self) -> dict[str, Any]:
        endpoints = self.endpoint_map()
        cfg = load_json_url(endpoints["config_url"])
        prefix = cfg.get("dataUrlPrefix", "data/")
        data_file = cfg.get("dataFile", "data.json")
        liste_file = cfg.get("listeFile", "liste.json")
        kandidati_file = cfg.get("vsiKandidatiFile", "kandidati.json")

        bundle: dict[str, Any] = {"config": cfg}
        bundle["data"] = load_json_url(self._url(f"{prefix}{data_file}"))
        bundle["liste"] = load_json_url(self._url(f"{prefix}{liste_file}"))

        try:
            bundle["kandidati"] = load_json_url(self._url(f"{prefix}{kandidati_file}"))
        except Exception:
            bundle["kandidati"] = []

        # Official election-day files documented by DVK for DZ 2026.
        bundle["udelezba_json"] = try_load_json_url(endpoints["udelezba_json_url"])
        bundle["rezultati_json"] = try_load_json_url(endpoints["rezultati_json_url"])
        bundle["kandidati_rezultat_json"] = try_load_json_url(endpoints["kandidati_rezultat_json_url"])
        bundle["udelezba_csv"] = try_load_text_url(endpoints["udelezba_csv_url"])
        bundle["rezultati_csv"] = try_load_text_url(endpoints["rezultati_csv_url"])
        bundle["mandati_csv"] = try_load_text_url(endpoints["mandati_csv_url"])

        bundle["source"] = {
            "base_url": self.base_url,
            "election": self.election,
            "endpoints": endpoints,
            "priority": [
                "rezultati.json + udelezba.json (official election-day JSON)",
                "rezultati.csv + udelezba.csv (official election-day CSV fallback)",
                "data.json + liste.json (legacy/app fallback)",
            ],
        }
        bundle["fetched_at"] = now_iso()
        return bundle


class TemplateCsv:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.rows = self._read_template(path)

    @staticmethod
    def _read_template(path: Path) -> list[list[str]]:
        rows: list[list[str]] = []
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line == "":
                rows.append([])
            else:
                parts = line.split(",")
                rows.append(parts)
        return rows

    def set_by_label(self, label: str, col_idx_1_based: int, value: str) -> bool:
        for row in self.rows:
            if row and row[0].strip() == label:
                while len(row) < col_idx_1_based:
                    row.append("")
                row[col_idx_1_based - 1] = value
                return True
        return False

    def rows_with_label(self) -> list[list[str]]:
        return [r for r in self.rows if r and r[0].strip()]

    def write(self, path: Path) -> None:
        lines = [",".join(r) if r else "" for r in self.rows]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def pick_result_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    sl = data.get("slovenija") or {}
    candidates = [
        sl.get("rez"),
        sl.get("rezultati"),
        data.get("rez"),
        data.get("rezultati"),
    ]
    for c in candidates:
        if isinstance(c, list):
            return [x for x in c if isinstance(x, dict)]
    return []


def collect_result_like_records(node: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        sid = node.get("st")
        has_percent = percent_from_record(node) is not None
        has_seats = seats_from_record(node) is not None
        if isinstance(sid, int) and (has_percent or has_seats):
            out.append(node)
        for v in node.values():
            collect_result_like_records(v, out)
    elif isinstance(node, list):
        for item in node:
            collect_result_like_records(item, out)


def map_lists(liste: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for x in liste:
        sid = x.get("st")
        if isinstance(sid, int):
            out[sid] = x
    return out


def percent_from_record(rec: dict[str, Any]) -> float | None:
    return deep_find_numeric(
        rec,
        ["odstotek", "odst", "delez", "proc", "pct", "percent", "procent"],
        int_like=False,
    )


def seats_from_record(rec: dict[str, Any]) -> int | None:
    return deep_find_numeric(
        rec,
        [
            "mandati",
            "mandatov",
            "mand",
            "sedezi",
            "st_mandatov",
            "st. mandatov",
            "št. mandatov",
            "st mandatov",
            "stmandatov",
            "poslanci",
        ],
        int_like=True,
    )


def find_list_id_for_label(label: str, list_by_id: dict[int, dict[str, Any]]) -> int | None:
    want = slug(label)
    for sid, lst in list_by_id.items():
        names = [str(lst.get("knaz", "")), str(lst.get("naz", ""))]
        for n in names:
            if not n:
                continue
            if slug(n) == want or want in slug(n) or slug(n) in want:
                return sid
    return None


def best_values_for_list(records: list[dict[str, Any]]) -> tuple[int | None, float | None]:
    seats: int | None = None
    pct: float | None = None
    for rec in records:
        if seats is None:
            seats = seats_from_record(rec)
        if pct is None:
            pct = percent_from_record(rec)
        if seats is not None and pct is not None:
            break
    return seats, pct


def extract_turnout_and_counted(data: dict[str, Any]) -> tuple[float | None, float | None]:
    sl = data.get("slovenija") or {}
    turnout = to_float(sl.get("udel"))
    counted = to_float(sl.get("prestetih_glasov"))
    if turnout is None:
        turnout = deep_find_numeric(sl, ["udel", "udelezba", "turnout"], int_like=False)
    if counted is None:
        counted = deep_find_numeric(sl, ["prestetih_glasov", "presteti", "counted"], int_like=False)
    return turnout, counted


def records_from_rezultati_json(rezultati_json: dict[str, Any], liste_by_id: dict[int, dict[str, Any]]) -> tuple[dict[int, tuple[int | None, float | None]], dict[str, Any]]:
    out: dict[int, tuple[int | None, float | None]] = {}
    sl = rezultati_json.get("slovenija")
    if isinstance(sl, list):
        for rec in sl:
            if not isinstance(rec, dict):
                continue
            sid = rec.get("st")
            if not isinstance(sid, int):
                continue
            seats = to_int(rec.get("man"))
            pct = to_float(rec.get("prc"))
            out[sid] = (seats, pct)

    glas = to_float(rezultati_json.get("glas"))
    velj = to_float(rezultati_json.get("velj"))
    nev = to_float(rezultati_json.get("nev"))
    return out, {"glas": glas, "velj": velj, "nev": nev}


def turnout_from_udelezba_json(udelezba_json: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    sl = udelezba_json.get("slovenija") if isinstance(udelezba_json, dict) else None
    if not isinstance(sl, dict):
        return None, None, None
    prc = to_float(sl.get("prc"))
    gl = to_float(sl.get("gl"))
    upr = to_float(sl.get("upr"))
    return prc, gl, upr


def parse_semicolon_csv_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(";")]
        rows.append(parts)
    return rows


def parse_number_maybe(value: str) -> float | None:
    return to_float(value.replace(".", "").replace(",", "."))


def parse_rezultati_csv_for_lists(csv_text: str, list_ids: set[int]) -> dict[int, tuple[int | None, float | None]]:
    rows = parse_semicolon_csv_rows(csv_text)
    out: dict[int, tuple[int | None, float | None]] = {}
    for r in rows:
        if len(r) < 4:
            continue
        sid = to_int(r[0])
        if sid is None or sid not in list_ids:
            continue
        # line shape: idx_liste ; st_prejetih_glasov ; odstotek_glasov ; st_prejetnih_mandatov
        pct = parse_number_maybe(r[2])
        seats = to_int(r[3])
        if pct is not None and pct > 1.0:
            pct = pct / 100.0
        out[sid] = (seats, pct)
    return out


def parse_rezultati_csv_slovenija_counted(csv_text: str) -> tuple[float | None, float | None]:
    rows = parse_semicolon_csv_rows(csv_text)
    for r in rows:
        if len(r) == 4:
            a = to_int(r[0])
            b = to_int(r[1])
            c = to_int(r[2])
            d = parse_number_maybe(r[3])
            if a is not None and b is not None and c is not None:
                return to_float(a), d
    return None, None


def parse_udelezba_csv_turnout(csv_text: str) -> tuple[float | None, float | None]:
    rows = parse_semicolon_csv_rows(csv_text)
    for r in rows:
        # Global line is expected right after date/time fields:
        # dd;mm;yyyy;hh;nn;upr;gl;prc
        if len(r) >= 8:
            gl = to_float(r[6])
            prc = parse_number_maybe(r[7])
            if prc is not None and prc > 1.0:
                prc = prc / 100.0
            return prc, gl
    return None, None


def fmt_percent(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.1f}"


def export_from_bundle(bundle: dict[str, Any], stoli_tpl_path: Path, udel_tpl_path: Path, output_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stoli_tpl = TemplateCsv(stoli_tpl_path)
    udel_tpl = TemplateCsv(udel_tpl_path)

    data = bundle["data"]
    liste = bundle.get("liste", [])
    records = pick_result_records(data)
    extra_records: list[dict[str, Any]] = []
    collect_result_like_records(data, extra_records)
    records.extend(extra_records)
    list_by_id = map_lists(liste if isinstance(liste, list) else [])
    records_by_st: dict[int, list[dict[str, Any]]] = {}
    for rec in records:
        sid = rec.get("st")
        if isinstance(sid, int):
            records_by_st.setdefault(sid, []).append(rec)

    status_rows: list[dict[str, Any]] = []

    results_source = "data.json fallback"
    turnout_source = "data.json fallback"
    counted_source = "data.json fallback"

    # Preferred documented election-day source: rezultati.json
    rez_json = bundle.get("rezultati_json")
    if isinstance(rez_json, dict) and isinstance(rez_json.get("slovenija"), list):
        map_from_rez_json, rez_meta = records_from_rezultati_json(rez_json, list_by_id)
        for sid, (seats, pct) in map_from_rez_json.items():
            if sid not in records_by_st:
                records_by_st[sid] = []
            records_by_st[sid].insert(0, {"st": sid, "man": seats, "prc": pct})
        results_source = "rezultati.json"
    else:
        rez_meta = {"glas": None, "velj": None, "nev": None}

    # CSV fallback for list seats/percent if rezultati.json is unavailable.
    if results_source != "rezultati.json":
        rez_csv = bundle.get("rezultati_csv")
        if isinstance(rez_csv, str) and rez_csv.strip():
            from_csv = parse_rezultati_csv_for_lists(rez_csv, set(list_by_id.keys()))
            if from_csv:
                for sid, (seats, pct) in from_csv.items():
                    if sid not in records_by_st:
                        records_by_st[sid] = []
                    records_by_st[sid].insert(0, {"st": sid, "man": seats, "prc": pct})
                results_source = "rezultati.csv"

    for row in stoli_tpl.rows_with_label():
        label = row[0].strip()
        if label.lower() == "manjšina":
            status_rows.append({"label": label, "list_id": None, "seats": None, "percentage": None, "note": "minority row"})
            continue
        list_id = find_list_id_for_label(label, list_by_id)
        recs = records_by_st.get(list_id, []) if list_id is not None else []
        seats, perc = best_values_for_list(recs)

        stoli_tpl.set_by_label(label, 2, "" if seats is None else str(seats))
        stoli_tpl.set_by_label(label, 4, fmt_percent(perc * 100.0 if perc is not None and perc <= 1.0 else perc))
        status_rows.append(
            {
                "label": label,
                "list_id": list_id,
                "records_found": len(recs),
                "seats": seats,
                "percentage": perc,
                "seats_status": "official" if seats is not None else "missing",
                "percentage_status": "official" if perc is not None else "missing",
            }
        )

    turnout, counted = extract_turnout_and_counted(data)

    # Preferred documented source for turnout: udelezba.json (slovenija.prc)
    u_json = bundle.get("udelezba_json")
    if isinstance(u_json, dict):
        uj_prc, uj_gl, _ = turnout_from_udelezba_json(u_json)
        if uj_prc is not None:
            turnout = uj_prc
            turnout_source = "udelezba.json"
        # count as documented: rezultati.glas / udelezba.slovenija.gl
        if rez_meta.get("glas") is not None and uj_gl not in (None, 0):
            counted = float(rez_meta["glas"]) / float(uj_gl)
            counted_source = "rezultati.json + udelezba.json formula"

    # CSV fallback
    if turnout_source != "udelezba.json":
        u_csv = bundle.get("udelezba_csv")
        if isinstance(u_csv, str) and u_csv.strip():
            c_prc, _c_gl = parse_udelezba_csv_turnout(u_csv)
            if c_prc is not None:
                turnout = c_prc
                turnout_source = "udelezba.csv"
    if counted_source == "data.json fallback":
        r_csv = bundle.get("rezultati_csv")
        if isinstance(r_csv, str) and r_csv.strip():
            counted_gl, _pct_valid = parse_rezultati_csv_slovenija_counted(r_csv)
            u_csv = bundle.get("udelezba_csv")
            c_prc, c_gl = parse_udelezba_csv_turnout(u_csv) if isinstance(u_csv, str) else (None, None)
            if counted_gl is not None and c_gl not in (None, 0):
                counted = float(counted_gl) / float(c_gl)
                counted_source = "rezultati.csv + udelezba.csv formula"

    udel_tpl.set_by_label("Udeležba", 2, fmt_percent(turnout * 100.0 if turnout is not None and turnout <= 1.0 else turnout))
    udel_tpl.set_by_label("Prešteti glasovi", 2, fmt_percent(counted * 100.0 if counted is not None and counted <= 1.0 else counted))

    out_stoli = output_dir / "stoli.csv"
    out_udel = output_dir / "udelezba.csv"
    status_path = output_dir / "export_status.json"
    stoli_tpl.write(out_stoli)
    udel_tpl.write(out_udel)
    status_payload = {
        "fetched_at": bundle.get("fetched_at"),
        "source": bundle.get("source", {}),
        "source_used": {
            "results": results_source,
            "turnout": turnout_source,
            "counted_votes": counted_source,
        },
        "dvk_nastavitve": (data.get("nastavitve") or {}),
        "turnout": turnout,
        "counted_votes": counted,
        "rows": status_rows,
    }
    status_path.write_text(json.dumps(status_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_stoli, out_udel, status_payload


def save_raw_bundle(bundle: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"dvk_raw_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def run_once(settings: Settings, dump_raw: bool = False) -> None:
    client = DVKClient(settings.base_url, settings.election)
    bundle = client.fetch_bundle()
    out_dir = Path(settings.output_dir)
    out_stoli, out_udel, status = export_from_bundle(
        bundle,
        Path(settings.stoli_template),
        Path(settings.udelezba_template),
        out_dir,
    )
    print(f"[{now_iso()}] Exported: {out_stoli} and {out_udel}")
    missing_seats = [r["label"] for r in status["rows"] if r.get("seats_status") == "missing"]
    if missing_seats:
        print(f"[{now_iso()}] Warning: seats missing for {len(missing_seats)} rows (see export_status.json).")
    if dump_raw:
        raw_path = save_raw_bundle(bundle, out_dir)
        print(f"[{now_iso()}] Saved raw DVK bundle: {raw_path}")


def run_watch(settings: Settings, dump_raw: bool = False) -> None:
    print(f"Starting watch mode: interval={settings.interval_seconds}s, election={settings.election}")
    while True:
        try:
            run_once(settings, dump_raw=dump_raw)
        except URLError as e:
            print(f"[{now_iso()}] Network error: {e}")
        except Exception as e:
            print(f"[{now_iso()}] Error: {e}")
        time.sleep(max(5, settings.interval_seconds))


def interactive_menu(settings: Settings, settings_path: Path) -> None:
    while True:
        print("\nDVK Exporter")
        print("1) Export now")
        print("2) Start automation loop")
        print("3) Save full DVK JSON dump now")
        print("4) Change settings")
        print("5) Save settings")
        print("0) Exit")
        choice = input("Select: ").strip()

        if choice == "1":
            run_once(settings)
        elif choice == "2":
            run_watch(settings)
        elif choice == "3":
            run_once(settings, dump_raw=True)
        elif choice == "4":
            settings.election = input(f"Election [{settings.election}]: ").strip() or settings.election
            settings.base_url = input(f"Base URL [{settings.base_url}]: ").strip() or settings.base_url
            settings.output_dir = input(f"Output dir [{settings.output_dir}]: ").strip() or settings.output_dir
            settings.stoli_template = input(f"stoli template [{settings.stoli_template}]: ").strip() or settings.stoli_template
            settings.udelezba_template = input(f"udelezba template [{settings.udelezba_template}]: ").strip() or settings.udelezba_template
            interval_in = input(f"Interval seconds [{settings.interval_seconds}]: ").strip()
            if interval_in:
                settings.interval_seconds = int(interval_in)
        elif choice == "5":
            settings.save(settings_path)
            print(f"Saved settings to {settings_path}")
        elif choice == "0":
            return
        else:
            print("Invalid option.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="DVK Slovenia election exporter for OBS/Expression CSV overlays.")
    p.add_argument("--settings", default=SETTINGS_FILE, help="Path to settings JSON file")

    sub = p.add_subparsers(dest="cmd")

    export = sub.add_parser("export", help="Run one export")
    export.add_argument("--dump-raw", action="store_true", help="Also save fetched DVK JSON bundle")

    watch = sub.add_parser("watch", help="Run continuous automatic export loop")
    watch.add_argument("--dump-raw", action="store_true", help="Also save fetched DVK JSON bundle each cycle")

    sub.add_parser("interactive", help="Interactive mode")
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    settings_path = Path(args.settings)
    settings = Settings.from_file(settings_path)

    try:
        if args.cmd == "export":
            run_once(settings, dump_raw=getattr(args, "dump_raw", False))
            return 0
        if args.cmd == "watch":
            run_watch(settings, dump_raw=getattr(args, "dump_raw", False))
            return 0
        interactive_menu(settings, settings_path)
        return 0
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except Exception as e:
        print(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
