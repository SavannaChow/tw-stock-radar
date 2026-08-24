# -*- coding: utf-8 -*-
"""Server-side, single-user watchlist persistence."""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime

from storage import runtime_path


WATCHLIST_FILE = runtime_path("watchlist.json")
MAX_ITEMS = 100
_CODE_RE = re.compile(r"^[0-9A-Za-z]{2,12}$")
_LOCK = threading.RLock()


def _clean(code: str, name: str = "") -> dict:
    code = (code or "").strip().upper()
    if not _CODE_RE.fullmatch(code):
        raise ValueError("股票代號格式不正確")
    return {
        "code": code,
        "name": (name or "").strip()[:80],
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }


def load() -> list[dict]:
    """Load normalized items. A damaged file degrades to an empty list."""
    with _LOCK:
        try:
            raw = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
            rows = raw.get("items", []) if isinstance(raw, dict) else raw
        except (OSError, ValueError, TypeError):
            rows = []
        out, seen = [], set()
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                item = _clean(row.get("code", ""), row.get("name", ""))
            except ValueError:
                continue
            if item["code"] in seen:
                continue
            item["added_at"] = row.get("added_at") or item["added_at"]
            seen.add(item["code"])
            out.append(item)
        return out[:MAX_ITEMS]


def _save(items: list[dict]) -> None:
    WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "items": items}
    tmp = WATCHLIST_FILE.with_name(WATCHLIST_FILE.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, WATCHLIST_FILE)


def add(code: str, name: str = "") -> tuple[list[dict], bool]:
    """Add or update one stock. Returns (items, created)."""
    item = _clean(code, name)
    with _LOCK:
        items = load()
        for old in items:
            if old["code"] == item["code"]:
                if item["name"] and old.get("name") != item["name"]:
                    old["name"] = item["name"]
                    _save(items)
                return items, False
        if len(items) >= MAX_ITEMS:
            raise ValueError(f"自選股最多 {MAX_ITEMS} 檔")
        items.append(item)
        _save(items)
        return items, True


def remove(code: str) -> tuple[list[dict], bool]:
    code = _clean(code)["code"]
    with _LOCK:
        items = load()
        kept = [x for x in items if x["code"] != code]
        removed = len(kept) != len(items)
        if removed:
            _save(kept)
        return kept, removed
