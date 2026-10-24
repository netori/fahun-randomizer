#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方案库（planlib）—— 保存 / 读取 / 管理随机方案

设计取舍（都围绕"这是用户的资产，丢了就是丢了"）：

* **一个方案一个 JSON**，放在 `<工作区>/plans/`。不放进 exe 内部 —— 重装 exe 不会丢方案。
* **原子写**：先写 `.tmp` 再 `os.replace`。断电/崩溃不会留下半截文件。
* **坏文件不拖垮整个库**：单个文件解析失败只跳过它，并在列表里标出来，其余照常可用。
* **指纹**：保存时记下全部行的 sha256。写入游戏前复核用（现有写入链本来就要求文件与方案对得上）。
* **名字归名字、id 归 id**：id 是文件名（安全字符），重命名只改 JSON 里的 name，不动文件 —— 
  这样"重命名"永远不会因为文件名冲突而失败或丢方案。
"""
import glob
import hashlib
import json
import os
import re
import time
import uuid

SCHEMA = 1
SUBDIR = "plans"

PLAN_FIELDS = ["pool", "role", "unit", "part", "old", "old_cat", "new", "new_cat",
               "source_table", "row_id", "slot", "row_name",
               "engine_version", "algorithm_mode", "unchanged_reason", "preconditions"]


class PlanError(Exception):
    pass


# ── 位置 ──────────────────────────────────────────────────────────────

def workspace_of(start=None):
    """从 start（或本文件）向上找带 investigation/apply 的工作区"""
    cur = os.path.abspath(start or os.path.dirname(os.path.abspath(__file__)))
    for _ in range(8):
        if os.path.isdir(os.path.join(cur, "investigation", "apply")):
            return cur
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt
    return None


def plans_dir(ws=None):
    ws = ws or workspace_of()
    if not ws:
        raise PlanError("找不到工作区")
    d = os.path.join(ws, SUBDIR)
    os.makedirs(d, exist_ok=True)
    return d


# ── 读写 ──────────────────────────────────────────────────────────────

def _atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def fingerprint(rows):
    """全部行的内容指纹（行序无关，避免 CSV 排序差异造成假不一致）"""
    h = hashlib.sha256()
    for r in sorted(rows, key=lambda x: (str(x.get("source_table", "")), str(x.get("row_id", "")),
                                         str(x.get("old", "")))):
        h.update(("|".join(str(r.get(k, "")) for k in
                           ("old", "new", "source_table", "row_id", "slot", "unit"))).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _safe_id(name):
    slug = re.sub(r"[^\w\u4e00-\u9fa5-]+", "_", (name or "plan").strip())[:28].strip("_") or "plan"
    return f"{time.strftime('%Y%m%d-%H%M%S')}_{slug}_{uuid.uuid4().hex[:6]}"


def _path(pid, ws=None):
    d = plans_dir(ws)
    if not re.fullmatch(r"[\w\u4e00-\u9fa5_\-]+", pid or ""):
        raise PlanError("方案 id 不合法")
    return os.path.join(d, pid + ".json")


def _meta(doc):
    rows = doc.get("rows") or []
    return {
        "id": doc.get("id"),
        "name": doc.get("name"),
        "note": doc.get("note", ""),
        "tags": doc.get("tags", []),
        "star": bool(doc.get("star")),
        "created": doc.get("created"),
        "modified": doc.get("modified"),
        "seed": doc.get("seed"),
        "rows": len(rows),
        "changed": sum(1 for r in rows if r.get("old") != r.get("new")),
        "fingerprint": doc.get("fingerprint"),
        "engine_version": doc.get("engine_version"),
        "cfg": doc.get("cfg") or {},
        "layer_dir": doc.get("layer_dir") or "",
        "kind": doc.get("kind") or "",
        "built": doc.get("built") or {},
        "broken": doc.get("_broken", False),
        "error": doc.get("_error", ""),
    }


def list_plans(ws=None, include_broken=True):
    """列出方案（默认按 收藏 → 修改时间 倒序）"""
    d = plans_dir(ws)
    out = []
    for fn in os.listdir(d):
        if not fn.endswith(".json") or fn.endswith(".tmp"):
            continue
        p = os.path.join(d, fn)
        try:
            doc = json.load(open(p, encoding="utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("不是对象")
            doc.setdefault("id", fn[:-5])
            out.append(_meta(doc))
        except Exception as e:
            if include_broken:
                out.append({"id": fn[:-5], "name": fn[:-5], "broken": True,
                            "error": f"{type(e).__name__}: {e}", "rows": 0, "changed": 0,
                            "star": False, "tags": [], "note": "", "created": None,
                            "modified": os.path.getmtime(p), "cfg": {}})
    out.sort(key=lambda m: (not m.get("star"), -(m.get("modified") or 0)))
    return out


def get_plan(pid, ws=None):
    p = _path(pid, ws)
    if not os.path.exists(p):
        raise PlanError(f"没有这个方案：{pid}")
    doc = json.load(open(p, encoding="utf-8"))
    doc.setdefault("id", pid)
    return doc


def save_plan(rows, name, cfg=None, seed=None, note="", tags=None, star=False, ws=None,
              kind=None):
    """保存一份方案。rows 是计划行（dict 列表），会完整存下来。

    2026-10-23：允许只随机敌人的方案（rows 为空）—— 以前必须有物品行才能存，
    于是「开始随机敌人」只能当场写层；现在敌人方案也只存方案库，覆盖层等开玩时再生成。
    """
    _enemy = bool(((cfg or {}).get("enemy_v1") or {}).get("on"))
    if not rows and not _enemy:
        raise PlanError("没有可保存的方案（先点底部的「开始随机…」）")
    name = (name or "").strip() or time.strftime("方案 %m-%d %H:%M")
    pid = _safe_id(name)
    now = time.time()
    doc = {
        "schema": SCHEMA,
        "id": pid,
        "name": name,
        "note": note or "",
        "tags": list(tags or []),
        "star": bool(star),
        "created": now,
        "modified": now,
        "seed": seed,
        "cfg": dict(cfg or {}),
        "kind": kind or ("both" if (rows and _enemy) else "enemy" if _enemy else "item"),
        "engine_version": (rows[0].get("engine_version") if rows else "") or "",
        "fingerprint": fingerprint(rows),
        "fields": PLAN_FIELDS,
        "rows": [{k: r.get(k, "") for k in PLAN_FIELDS} for r in rows],
    }
    _atomic_write(_path(pid, ws), json.dumps(doc, ensure_ascii=False, indent=1))
    return _meta(doc)


def rename_plan(pid, new_name, ws=None):
    doc = get_plan(pid, ws)
    new_name = (new_name or "").strip()
    if not new_name:
        raise PlanError("名字不能为空")
    doc["name"] = new_name
    doc["modified"] = time.time()
    _atomic_write(_path(pid, ws), json.dumps(doc, ensure_ascii=False, indent=1))
    return _meta(doc)


def set_meta(pid, star=None, note=None, tags=None, layer_dir=None, built=None, ws=None):
    doc = get_plan(pid, ws)
    if star is not None:
        doc["star"] = bool(star)
    if note is not None:
        doc["note"] = note
    if tags is not None:
        doc["tags"] = list(tags)
    if layer_dir is not None:
        # 这个方案对应的"覆盖层"目录（YAFSML 用；由部署时产出并回写到这里）
        doc["layer_dir"] = layer_dir or ""
    if built is not None:
        # 这份覆盖层是按哪个版本的方案生成的（指纹不同 = 设置改过，下次开玩要重建）
        doc["built"] = dict(built or {})
    doc["modified"] = time.time()
    _atomic_write(_path(pid, ws), json.dumps(doc, ensure_ascii=False, indent=1))
    return _meta(doc)


def duplicate_plan(pid, new_name=None, ws=None):
    doc = get_plan(pid, ws)
    doc["name"] = (new_name or (doc["name"] + " · 副本")).strip()
    doc["id"] = _safe_id(doc["name"])
    doc["created"] = doc["modified"] = time.time()
    _atomic_write(_path(doc["id"], ws), json.dumps(doc, ensure_ascii=False, indent=1))
    return _meta(doc)


def delete_plan(pid, ws=None):
    """删除。为防手滑，同时留一份到 plans/.trash/（可手动找回）"""
    p = _path(pid, ws)
    if not os.path.exists(p):
        raise PlanError(f"没有这个方案：{pid}")
    trash = os.path.join(plans_dir(ws), ".trash")
    os.makedirs(trash, exist_ok=True)
    os.replace(p, os.path.join(trash, os.path.basename(p)))
    return True


def mode_of(pid, ws=None):
    """这个方案是不是"商店也参与"生成的（从 cfg 判断，用于提示）"""
    cfg = (get_plan(pid, ws).get("cfg") or {})
    return bool(cfg.get("shops"))


def export_plan(pid, dest_path, ws=None):
    doc = get_plan(pid, ws)
    _atomic_write(dest_path, json.dumps(doc, ensure_ascii=False, indent=1))
    return dest_path


def import_plan(src_path, ws=None, new_name=None):
    doc = json.load(open(src_path, encoding="utf-8"))
    if not isinstance(doc, dict) or not doc.get("rows"):
        raise PlanError("这个文件不是方案文件")
    doc["name"] = (new_name or doc.get("name") or os.path.basename(src_path)).strip()
    doc["id"] = _safe_id(doc["name"])
    doc["created"] = doc["modified"] = time.time()
    _atomic_write(_path(doc["id"], ws), json.dumps(doc, ensure_ascii=False, indent=1))
    return _meta(doc)


def write_csv(pid, dest_path, ws=None):
    """把方案导出成写入链认识的 CSV（它要 BOM，见现有 out/*.csv）"""
    import csv
    doc = get_plan(pid, ws)
    rows = doc.get("rows") or []
    fields = doc.get("fields") or PLAN_FIELDS
    with open(dest_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    return dest_path


def verify_plan_rows(pid, rows, ws=None):
    """拿一份刚生成的行和一份已存方案比对（用于"载入后是否与当前一致"的提示）"""
    doc = get_plan(pid, ws)
    a = fingerprint(doc.get("rows") or [])
    b = fingerprint(rows)
    return a == b, a, b


def deploys_for(fingerprint, ws=None):
    """这个指纹的方案写入过几次（按 logs/deploy_*.json 里的 fingerprint 找），返回时间戳列表（新到旧）。

    收据里记 fingerprint 是 2026-10-14 加的 —— 更老的收据没有这个字段，自然匹配不上。
    """
    if not fingerprint:
        return []
    root = ws or workspace_of()
    if not root:
        return []
    out = []
    for f in sorted(glob.glob(os.path.join(root, "logs", "deploy_*.json")), reverse=True):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if d.get("fingerprint") == fingerprint:
            out.append(d.get("ts_epoch") or 0)
    return [x for x in out if x]
