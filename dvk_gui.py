from __future__ import annotations

import csv
import io
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from dvk_exporter import DVKClient, Settings, run_once


APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = APP_DIR / "settings.json"
AUTO_LOG_PATH = APP_DIR / "automation.log"
STATUS_PATH = APP_DIR / "export_status.json"


def log_line(message: str) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    AUTO_LOG_PATH.write_text(
        (AUTO_LOG_PATH.read_text(encoding="utf-8") if AUTO_LOG_PATH.exists() else "") + f"[{ts}] {message}\n",
        encoding="utf-8",
    )


def automation_worker(settings_dict: dict, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        settings = Settings(**settings_dict)
        try:
            run_once(settings)
            log_line("Auto export completed.")
        except Exception as exc:
            log_line(f"Auto export failed: {exc}")
        stop_event.wait(max(5, settings.interval_seconds))


def ensure_state() -> None:
    if "auto_thread" not in st.session_state:
        st.session_state.auto_thread = None
    if "auto_stop_event" not in st.session_state:
        st.session_state.auto_stop_event = None
    if "auto_running" not in st.session_state:
        st.session_state.auto_running = False
    if "custom_bundle" not in st.session_state:
        st.session_state.custom_bundle = None
    if "custom_paths" not in st.session_state:
        st.session_state.custom_paths = []


def flatten_json(node: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.update(flatten_json(v, p))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            p = f"{prefix}[{i}]"
            out.update(flatten_json(v, p))
    else:
        out[prefix] = node
    return out


def get_by_path(node: Any, path: str) -> Any:
    cursor = node
    tokens: list[str] = []
    buf = ""
    i = 0
    while i < len(path):
        ch = path[i]
        if ch == ".":
            if buf:
                tokens.append(buf)
                buf = ""
            i += 1
            continue
        if ch == "[":
            if buf:
                tokens.append(buf)
                buf = ""
            j = path.find("]", i)
            if j == -1:
                raise ValueError(f"Invalid path: {path}")
            tokens.append(path[i : j + 1])
            i = j + 1
            continue
        buf += ch
        i += 1
    if buf:
        tokens.append(buf)

    for tok in tokens:
        if tok.startswith("[") and tok.endswith("]"):
            idx = int(tok[1:-1])
            if not isinstance(cursor, list) or idx >= len(cursor):
                return None
            cursor = cursor[idx]
        else:
            if not isinstance(cursor, dict):
                return None
            cursor = cursor.get(tok)
            if cursor is None:
                return None
    return cursor


def to_csv(rows: list[dict[str, Any]], delimiter: str = ",") -> str:
    if not rows:
        return ""
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for k in row.keys():
            if k not in seen:
                seen.add(k)
                fieldnames.append(k)
    sio = io.StringIO()
    writer = csv.DictWriter(sio, fieldnames=fieldnames, delimiter=delimiter)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return sio.getvalue()


def start_automation(settings: Settings) -> None:
    if st.session_state.auto_running:
        return
    stop_event = threading.Event()
    thread = threading.Thread(
        target=automation_worker,
        args=(settings.__dict__.copy(), stop_event),
        daemon=True,
    )
    st.session_state.auto_stop_event = stop_event
    st.session_state.auto_thread = thread
    st.session_state.auto_running = True
    log_line("Automation started.")
    thread.start()


def stop_automation() -> None:
    if not st.session_state.auto_running:
        return
    if st.session_state.auto_stop_event is not None:
        st.session_state.auto_stop_event.set()
    if st.session_state.auto_thread is not None:
        st.session_state.auto_thread.join(timeout=1.5)
    st.session_state.auto_running = False
    st.session_state.auto_thread = None
    st.session_state.auto_stop_event = None
    log_line("Automation stopped.")


def render_file_preview(path: Path, title: str) -> None:
    st.subheader(title)
    if not path.exists():
        st.info(f"`{path}` does not exist yet.")
        return
    st.code(path.read_text(encoding="utf-8-sig"), language="text")


def render_custom_builder(settings: Settings) -> None:
    st.subheader("Custom export builder")
    st.caption("Browse DVK fields, pick your own fields, export as CSV or JSON.")

    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("Load latest DVK data", use_container_width=True):
            try:
                client = DVKClient(settings.base_url, settings.election)
                bundle = client.fetch_bundle()
                st.session_state.custom_bundle = bundle
                flat = flatten_json(bundle)
                st.session_state.custom_paths = sorted(flat.keys())
                st.success(f"Loaded DVK bundle with {len(st.session_state.custom_paths)} scalar fields.")
            except Exception as exc:
                st.error(f"Load failed: {exc}")
    with c2:
        if st.button("Use last raw export file", use_container_width=True):
            candidates = sorted(APP_DIR.glob("dvk_raw_*.json"), reverse=True)
            if not candidates:
                st.warning("No raw export files found. Run 'Export now + raw JSON' first.")
            else:
                try:
                    bundle = json.loads(candidates[0].read_text(encoding="utf-8"))
                    st.session_state.custom_bundle = bundle
                    flat = flatten_json(bundle)
                    st.session_state.custom_paths = sorted(flat.keys())
                    st.success(f"Loaded {candidates[0].name} with {len(st.session_state.custom_paths)} scalar fields.")
                except Exception as exc:
                    st.error(f"Failed to load raw export: {exc}")

    if not st.session_state.custom_bundle:
        st.info("Load DVK data first to build custom exports.")
        return

    all_paths = st.session_state.custom_paths
    query = st.text_input("Field search", value="")
    visible_paths = [p for p in all_paths if query.lower() in p.lower()] if query else all_paths

    selected_paths = st.multiselect(
        "Select fields",
        options=visible_paths,
        default=visible_paths[: min(10, len(visible_paths))],
    )

    format_choice = st.selectbox("Output format", ["CSV", "JSON"])
    style_choice = st.selectbox(
        "Output style",
        [
            "Single record",
            "Key-value rows",
            "Pretty JSON",
        ],
    )
    delimiter = st.selectbox("CSV delimiter", [",", ";", "\t"], index=0)
    custom_name = st.text_input("Output filename (without extension)", value="custom_export")

    bundle = st.session_state.custom_bundle
    selected_data = {p: get_by_path(bundle, p) for p in selected_paths}

    if style_choice == "Single record":
        rows = [selected_data]
    elif style_choice == "Key-value rows":
        rows = [{"path": k, "value": v} for k, v in selected_data.items()]
    else:
        rows = []

    if format_choice == "JSON":
        if style_choice == "Pretty JSON":
            payload = selected_data
        else:
            payload = rows
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        ext = "json"
        mime = "application/json"
    else:
        content = to_csv(rows, delimiter=delimiter)
        ext = "csv"
        mime = "text/csv"

    output_path = Path(settings.output_dir) / f"{custom_name}.{ext}"
    a1, a2 = st.columns(2)
    with a1:
        if st.button("Save custom export to output folder", use_container_width=True):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content, encoding="utf-8-sig" if ext == "csv" else "utf-8")
            st.success(f"Saved: {output_path}")
    with a2:
        st.download_button(
            "Download custom export",
            data=content,
            file_name=f"{custom_name}.{ext}",
            mime=mime,
            use_container_width=True,
        )

    st.caption("Preview")
    st.code(content[:20000] if content else "(empty)", language="json" if ext == "json" else "text")


def render_data_sources(settings: Settings) -> None:
    st.subheader("Data sources (exact endpoints)")
    try:
        client = DVKClient(settings.base_url, settings.election)
        endpoints = client.endpoint_map()
        source_obj = {
            "base_url": settings.base_url,
            "election": settings.election,
            "endpoints": endpoints,
        }
        st.code(json.dumps(source_obj, ensure_ascii=False, indent=2), language="json")
    except Exception as exc:
        st.error(f"Failed to resolve endpoints: {exc}")

    if STATUS_PATH.exists():
        try:
            status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
            st.caption("Last export source metadata")
            st.code(
                json.dumps(
                    {
                        "fetched_at": status.get("fetched_at"),
                        "source": status.get("source", {}),
                        "dvk_nastavitve": status.get("dvk_nastavitve", {}),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                language="json",
            )
        except Exception as exc:
            st.warning(f"Could not read export_status.json: {exc}")


def main() -> None:
    st.set_page_config(page_title="DVK Exporter GUI", page_icon="🗳️", layout="wide")
    ensure_state()

    if st.session_state.auto_running and st.session_state.auto_thread and not st.session_state.auto_thread.is_alive():
        st.session_state.auto_running = False
        st.session_state.auto_thread = None
        st.session_state.auto_stop_event = None

    st.title("DVK Election Exporter")
    st.caption("Modern GUI for DVK -> OBS/Expression CSV exports")

    settings = Settings.from_file(SETTINGS_PATH)

    with st.sidebar:
        st.header("Settings")
        election = st.text_input("Election", value=settings.election)
        base_url = st.text_input("Base URL", value=settings.base_url)
        output_dir = st.text_input("Output directory", value=settings.output_dir)
        stoli_template = st.text_input("stoli template path", value=settings.stoli_template)
        udelezba_template = st.text_input("udelezba template path", value=settings.udelezba_template)
        interval_seconds = st.number_input(
            "Automation interval (seconds)",
            min_value=5,
            max_value=3600,
            value=max(5, int(settings.interval_seconds)),
            step=5,
        )

        new_settings = Settings(
            election=election,
            base_url=base_url,
            output_dir=output_dir,
            stoli_template=stoli_template,
            udelezba_template=udelezba_template,
            interval_seconds=int(interval_seconds),
        )

        if st.button("Save settings", use_container_width=True):
            new_settings.save(SETTINGS_PATH)
            st.success("Settings saved.")

    tab_main, tab_custom = st.tabs(["Election exports", "Custom builder"])

    with tab_main:
        render_data_sources(new_settings)
        st.divider()
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Export now", use_container_width=True):
                try:
                    run_once(new_settings)
                    st.success("Export completed.")
                except Exception as exc:
                    st.error(f"Export failed: {exc}")
        with c2:
            if st.button("Export now + raw JSON", use_container_width=True):
                try:
                    run_once(new_settings, dump_raw=True)
                    st.success("Export + raw JSON completed.")
                except Exception as exc:
                    st.error(f"Export failed: {exc}")
        with c3:
            if st.button("Refresh previews", use_container_width=True):
                st.rerun()

        st.divider()
        st.subheader("Automation")
        state_text = "Running" if st.session_state.auto_running else "Stopped"
        st.write(f"Status: **{state_text}**")

        a1, a2 = st.columns(2)
        with a1:
            if st.button("Start automation", use_container_width=True, disabled=st.session_state.auto_running):
                start_automation(new_settings)
                st.success("Automation started.")
        with a2:
            if st.button("Stop automation", use_container_width=True, disabled=not st.session_state.auto_running):
                stop_automation()
                st.warning("Automation stopped.")

        if AUTO_LOG_PATH.exists():
            st.caption("Automation log")
            st.code(AUTO_LOG_PATH.read_text(encoding="utf-8"), language="text")

        st.divider()
        st.subheader("Export data status")
        if STATUS_PATH.exists():
            st.code(STATUS_PATH.read_text(encoding="utf-8"), language="json")
        else:
            st.info("No `export_status.json` yet. Click Export now first.")

        st.divider()
        left, right = st.columns(2)
        with left:
            render_file_preview(APP_DIR / "stoli.csv", "stoli.csv preview")
        with right:
            render_file_preview(APP_DIR / "udelezba.csv", "udelezba.csv preview")

    with tab_custom:
        render_custom_builder(new_settings)


if __name__ == "__main__":
    main()
