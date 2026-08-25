# -*- coding: utf-8 -*-
"""Server-side, single-user watchlist persistence."""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime

from storage import runtime_path


WATCHLIST_FILE = runtime_path("watchlist.json")
MAX_ITEMS = 100
MAX_GROUPS = 20
MAX_GROUP_NAME = 24
DEFAULT_GROUP_ID = "default"
DEFAULT_GROUP_NAME = "未分類"
_CODE_RE = re.compile(r"^[0-9A-Za-z]{2,12}$")
_GROUP_ID_RE = re.compile(r"^(?:default|g_[0-9a-f]{12})$")
_LOCK = threading.RLock()


def _clean(code: str, name: str = "", group_id: str = DEFAULT_GROUP_ID) -> dict:
    code = (code or "").strip().upper()
    if not _CODE_RE.fullmatch(code):
        raise ValueError("股票代號格式不正確")
    group_id = (group_id or DEFAULT_GROUP_ID).strip().lower()
    if not _GROUP_ID_RE.fullmatch(group_id):
        group_id = DEFAULT_GROUP_ID
    return {
        "code": code,
        "name": (name or "").strip()[:80],
        "group_id": group_id,
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }


def _default_group() -> dict:
    return {"id": DEFAULT_GROUP_ID, "name": DEFAULT_GROUP_NAME, "sort_order": 10_000}


def _clean_group_name(name: str) -> str:
    name = " ".join((name or "").strip().split())
    if not name:
        raise ValueError("分類名稱不可空白")
    if len(name) > MAX_GROUP_NAME:
        raise ValueError(f"分類名稱最多 {MAX_GROUP_NAME} 個字")
    if any(ord(ch) < 32 for ch in name):
        raise ValueError("分類名稱含有不允許的控制字元")
    return name


def _normalize(raw) -> dict:
    """Normalize version 1/list payloads into version 2 without discarding stocks."""
    raw_items = raw.get("items", []) if isinstance(raw, dict) else raw
    raw_groups = raw.get("groups", []) if isinstance(raw, dict) else []

    groups: list[dict] = []
    group_ids = {DEFAULT_GROUP_ID}
    group_names = {DEFAULT_GROUP_NAME.casefold()}
    for index, row in enumerate(raw_groups if isinstance(raw_groups, list) else []):
        if not isinstance(row, dict):
            continue
        group_id = str(row.get("id") or "").strip().lower()
        if group_id == DEFAULT_GROUP_ID or not _GROUP_ID_RE.fullmatch(group_id) or group_id in group_ids:
            continue
        try:
            name = _clean_group_name(str(row.get("name") or ""))
        except ValueError:
            continue
        if name.casefold() in group_names:
            continue
        try:
            sort_order = int(row.get("sort_order", index))
        except (TypeError, ValueError):
            sort_order = index
        groups.append({"id": group_id, "name": name, "sort_order": sort_order,
                       "created_at": row.get("created_at")})
        group_ids.add(group_id)
        group_names.add(name.casefold())
        if len(groups) >= MAX_GROUPS:
            break
    groups.sort(key=lambda x: (x["sort_order"], x["name"]))
    for index, group in enumerate(groups):
        group["sort_order"] = index
        if not group.get("created_at"):
            group.pop("created_at", None)
    groups.append(_default_group())

    items, seen = [], set()
    for row in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            item = _clean(row.get("code", ""), row.get("name", ""), row.get("group_id"))
        except ValueError:
            continue
        if item["code"] in seen:
            continue
        if item["group_id"] not in group_ids:
            item["group_id"] = DEFAULT_GROUP_ID
        item["added_at"] = row.get("added_at") or item["added_at"]
        seen.add(item["code"])
        items.append(item)
    return {"version": 2, "groups": groups, "items": items[:MAX_ITEMS]}


def load_data() -> dict:
    """Load groups + items. Version 1 and damaged files degrade safely."""
    with _LOCK:
        try:
            raw = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            raw = []
        return _normalize(raw)


def load() -> list[dict]:
    """Backward-compatible item-only view used by existing callers."""
    return load_data()["items"]


def _save_data(data: dict) -> None:
    WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = _normalize(data)
    tmp = WATCHLIST_FILE.with_name(WATCHLIST_FILE.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, WATCHLIST_FILE)


def add(code: str, name: str = "", group_id: str | None = None) -> tuple[list[dict], bool]:
    """Add or update one stock. Returns (items, created)."""
    item = _clean(code, name, group_id or DEFAULT_GROUP_ID)
    with _LOCK:
        data = load_data()
        items = data["items"]
        valid_groups = {group["id"] for group in data["groups"]}
        if group_id is not None and item["group_id"] not in valid_groups:
            raise ValueError("指定的自選股分類不存在")
        for old in items:
            if old["code"] == item["code"]:
                changed = False
                if item["name"] and old.get("name") != item["name"]:
                    old["name"] = item["name"]
                    changed = True
                if group_id is not None and old.get("group_id") != item["group_id"]:
                    old["group_id"] = item["group_id"]
                    changed = True
                if changed:
                    _save_data(data)
                return items, False
        if len(items) >= MAX_ITEMS:
            raise ValueError(f"自選股最多 {MAX_ITEMS} 檔")
        items.append(item)
        _save_data(data)
        return items, True


def remove(code: str) -> tuple[list[dict], bool]:
    code = _clean(code)["code"]
    with _LOCK:
        data = load_data()
        items = data["items"]
        kept = [x for x in items if x["code"] != code]
        removed = len(kept) != len(items)
        if removed:
            data["items"] = kept
            _save_data(data)
        return kept, removed


def create_group(name: str) -> dict:
    name = _clean_group_name(name)
    with _LOCK:
        data = load_data()
        custom = [g for g in data["groups"] if g["id"] != DEFAULT_GROUP_ID]
        if len(custom) >= MAX_GROUPS:
            raise ValueError(f"自選股分類最多 {MAX_GROUPS} 個")
        if any(g["name"].casefold() == name.casefold() for g in data["groups"]):
            raise ValueError("分類名稱已存在")
        group = {"id": f"g_{uuid.uuid4().hex[:12]}", "name": name,
                 "sort_order": len(custom),
                 "created_at": datetime.now().isoformat(timespec="seconds")}
        data["groups"].insert(len(custom), group)
        _save_data(data)
        return load_data()


def rename_group(group_id: str, name: str) -> dict:
    name = _clean_group_name(name)
    if group_id == DEFAULT_GROUP_ID:
        raise ValueError("未分類不可重新命名")
    with _LOCK:
        data = load_data()
        if any(g["name"].casefold() == name.casefold() and g["id"] != group_id
               for g in data["groups"]):
            raise ValueError("分類名稱已存在")
        group = next((g for g in data["groups"] if g["id"] == group_id), None)
        if group is None:
            raise ValueError("自選股分類不存在")
        group["name"] = name
        _save_data(data)
        return load_data()


def delete_group(group_id: str) -> dict:
    if group_id == DEFAULT_GROUP_ID:
        raise ValueError("未分類不可刪除")
    with _LOCK:
        data = load_data()
        if not any(g["id"] == group_id for g in data["groups"]):
            raise ValueError("自選股分類不存在")
        data["groups"] = [g for g in data["groups"] if g["id"] != group_id]
        for item in data["items"]:
            if item.get("group_id") == group_id:
                item["group_id"] = DEFAULT_GROUP_ID
        _save_data(data)
        return load_data()


def move(code: str, group_id: str) -> dict:
    code = _clean(code)["code"]
    group_id = (group_id or "").strip().lower()
    with _LOCK:
        data = load_data()
        if not any(g["id"] == group_id for g in data["groups"]):
            raise ValueError("自選股分類不存在")
        item = next((x for x in data["items"] if x["code"] == code), None)
        if item is None:
            raise ValueError("自選股不存在")
        item["group_id"] = group_id
        _save_data(data)
        return load_data()
