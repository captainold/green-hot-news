#!/usr/bin/env python3
"""Health tracker — append source-health snapshots to admin/data/.

Reads data/source-status.json (written by update_news.py every run) and appends
one history entry (dedup by timestamp), keeping the last MAX_ENTRIES (96h at a
30-min cadence). Also writes admin/data/health-now.json with server-side status
(timer / journal / disk / git) for the admin dashboard.

Outputs are placed under admin/data/ so that nginx Basic Auth (location /admin/)
protects them — do NOT put them in data/ (publicly served).
Pure stdlib, zero deps. Run after update_news.py in the sync script.
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADMIN_DATA = ROOT / "admin" / "data"
HISTORY_FILE = ADMIN_DATA / "health-history.json"
NOW_FILE = ADMIN_DATA / "health-now.json"
MAX_ENTRIES = 192  # 96 hours at 30-min cadence
BEIJING = timezone(timedelta(hours=8))


def run(cmd: list[str], timeout: int = 10) -> str | None:
    """Best-effort subprocess call; returns trimmed stdout or None on failure."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "").strip()
        return out or (r.stderr or "").strip() or None
    except Exception:
        return None


def main() -> int:
    status_file = ROOT / "data" / "source-status.json"
    if not status_file.exists():
        print("health: source-status.json missing — nothing to track")
        return 0

    try:
        status = json.loads(status_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"health: cannot parse source-status.json: {e}")
        return 1

    sites = status.get("sites", [])
    now = datetime.now(BEIJING)
    ts = now.strftime("%Y-%m-%d %H:%M")

    entry = {
        "ts": ts,
        "ok": sum(1 for s in sites if s.get("ok")),
        "fail": sum(1 for s in sites if not s.get("ok")),
        "raw": status.get("total_raw_items", 0),
        "green": status.get("total_green_items", 0),
        # per-site: {"id": [ok, count]} compact tuple
        "sites": {s["site_id"]: [bool(s.get("ok")), int(s.get("item_count", 0))] for s in sites},
    }

    # ── history (append / dedupe same-ts) ────────────────────────────────
    history = {"entries": []}
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            history = {"entries": []}
    entries = history.get("entries", [])
    if entries and entries[-1].get("ts") == ts:
        entries[-1] = entry
    else:
        entries.append(entry)
    entries = entries[-MAX_ENTRIES:]
    history = {"updated_at": ts, "entries": entries}
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")

    # ── server-side status (best effort; null on local runs) ─────────────
    server = {
        "timer_active": run(["systemctl", "is-active", "green-policy.timer"]),
        "last_log": run(
            ["journalctl", "-u", "green-policy.service", "--no-pager", "-n", "12"]
        ),
        "disk": run(["df", "-h", "/opt"]),
        "notes_commit": run(
            [
                "git", "-C", str(ROOT / "Notes"), "log", "-1",
                "--format=%cd %h %s", "--date=format:%Y-%m-%d %H:%M",
            ]
        ),
        "site_commit": run(
            [
                "git", "-C", str(ROOT), "log", "-1",
                "--format=%cd %h %s", "--date=format:%Y-%m-%d %H:%M",
            ]
        ),
        "generated_at": status.get("generated_at"),
    }

    now_json = {
        "generated_at": ts,
        "status": status,
        "server": server,
    }
    NOW_FILE.parent.mkdir(parents=True, exist_ok=True)
    NOW_FILE.write_text(
        json.dumps(now_json, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(f"health: {ts} ok={entry['ok']} fail={entry['fail']} green={entry['green']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
