#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_nexus_upload.py — 用 N 网官方 API 给「已存在的 mod」上传文件

   依据：https://api.nexusmods.com/openapi.yaml（官方规范，逐条对着写的）

   安全约定（重要）：
     · API key 只从**环境变量** NEXUS_API_KEY 读取 —— 不接受命令行参数、不写进任何文件
     · 全程不打印 key 明文（只显示前 4 位用于确认）
     · 不做「创建 mod」——API 里没有这个端点，mod 页必须先由你在网页上建好

   用法：
     set NEXUS_API_KEY=你的key            （PowerShell: $env:NEXUS_API_KEY="你的key"）

     python _nexus_upload.py --check
     python _nexus_upload.py --list --mod-id 1234567
     python _nexus_upload.py --mod-id 1234567 --file xxx.exe --name "显示名" --version 1.0.0

   流程（对应 N 网规范里的四步）：
     ① POST /uploads                       建上传会话 → 拿 presigned_url
     ② PUT  <presigned_url>                把文件二进制发上去
     ③ GET  /uploads/{id}                  轮询到 state=available
     ④ POST /mod-files                     变成 mod 里的一个文件
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://api.nexusmods.com/v3"
KEY_ENV = "NEXUS_API_KEY"


def key_or_die():
    k = os.environ.get(KEY_ENV, "").strip()
    if not k:
        print(f"  ✗ 环境变量 {KEY_ENV} 没设置。先设置再跑（不用发给我）：")
        print(f"      CMD         : set {KEY_ENV}=你的key")
        print(f"      PowerShell  : $env:{KEY_ENV}=\"你的key\"")
        print(f"      永久设置     : setx {KEY_ENV} \"你的key\"")
        sys.exit(2)
    return k


def masked(k):
    return f"{k[:4]}…{k[-2:]}" if len(k) > 8 else "（已设置）"


def call(method, path, key, body=None, raw_to=None, extra_headers=None, timeout=120):
    """调 API。raw_to 不为空则把响应体当二进制写到该路径（用于下载 presigned 内容）"""
    headers = {"apikey": key, "Accept": "application/json",
               "User-Agent": "nexus-upload-script/1.0"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(BASE + path if path.startswith("/") else path,
                                 data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if raw_to:
                open(raw_to, "wb").write(raw)
                return r.status, None
            try:
                return r.status, json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return r.status, {"_raw": raw.decode("utf-8", "replace")[:400]}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        return e.code, {"_error": detail}
    except Exception as e:
        return 0, {"_error": f"{type(e).__name__}: {e}"}


def put_file(url, path, timeout=900):
    """把文件 PUT 到 presigned URL（S3）。注意：别加 Content-Type 之外的额外头"""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        req = urllib.request.Request(url, data=f.read(), method="PUT",
                                     headers={"Content-Length": str(size)})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, ""
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")[:300]
        except Exception as e:
            return 0, f"{type(e).__name__}: {e}"


def show(title, obj):
    print(f"  {title}")
    if isinstance(obj, dict):
        print("    " + json.dumps(obj, ensure_ascii=False, indent=2)[:900].replace("\n", "\n    "))
    else:
        print(f"    {obj}")


def main():
    ap = argparse.ArgumentParser(description="N 网上传（给已存在的 mod）")
    ap.add_argument("--check", action="store_true", help="只检查 key 与连通性")
    ap.add_argument("--list", action="store_true", help="列出该 mod 已有的文件")
    ap.add_argument("--mod-id", help="mod 页地址里的数字（创建 mod 必须先在网页做）")
    ap.add_argument("--file", help="要上传的文件路径")
    ap.add_argument("--name", help="文件显示名（不给就用文件名）")
    ap.add_argument("--version", default="1.0.0", help="版本号")
    ap.add_argument("--desc", default="", help="文件说明")
    ap.add_argument("--category", default="main",
                    choices=["main", "optional", "miscellaneous", "old_version", "archived"],
                    help="文件分类")
    a = ap.parse_args()
    key = key_or_die()
    print(f"  API   : {BASE}")
    print(f"  Key   : {masked(key)}（只从环境变量读，不落盘、不打印明文）")

    if a.check:
        if not a.mod_id:
            print("\n  ✓ key 已设置。要真正验证，请带上 --mod-id 再跑一次（会读一次 mod 详情）")
            return 0
        st, d = call("GET", f"/games/eldenring/mods/{a.mod_id}", key)
        print(f"\n  GET /games/eldenring/mods/{a.mod_id} → HTTP {st}")
        if st == 200:
            print("  ✓ key 有效，mod 也找得到")
            show("mod 信息:", {k: d.get(k) for k in ("name", "summary", "status") if isinstance(d, dict)})
            return 0
        show("响应:", d)
        return 1

    if not a.mod_id:
        print("\n  ✗ 需要 --mod-id。mod 页地址里的那串数字：")
        print("      https://www.nexusmods.com/eldenring/mods/1234567  ← 1234567")
        print("      注意：API **不能创建 mod 页**，必须先由你在网页上建好。")
        return 2

    if a.list:
        st, d = call("GET", f"/mods/{a.mod_id}/files", key)
        print(f"\n  GET /mods/{a.mod_id}/files → HTTP {st}")
        show("文件列表:", d)
        return 0 if st == 200 else 1

    if not a.file or not os.path.exists(a.file):
        print(f"\n  ✗ 文件不存在：{a.file}")
        return 2
    size = os.path.getsize(a.file)
    name = a.name or os.path.basename(a.file)
    print(f"\n  待上传: {os.path.basename(a.file)}  {size/1048576:.1f} MB  → mod {a.mod_id}")

    # ① 建上传会话
    st, d = call("POST", "/uploads", key, {"size_bytes": size, "filename": os.path.basename(a.file)})
    print(f"\n  ① POST /uploads → HTTP {st}")
    if st not in (200, 201):
        show("失败:", d)
        return 1
    data = d.get("data", d)
    up_id = data.get("id") or (data.get("upload") or {}).get("id")
    if not up_id:
        show("返回里没有 id，原样贴给你看:", d)
        return 1
    print(f"     上传会话 id: {up_id}")

    # ② 传二进制
    if data.get("presigned_url"):
        print("  （单段上传）")
        st2, err = put_file(data["presigned_url"], a.file)
        print(f"  ② PUT 文件 → HTTP {st2}")
        if st2 not in (200, 204):
            print(f"     失败: {err}")
            return 1
    else:
        print("  ⚠ 返回是**分片上传**（part_presigned_urls）—— 这个脚本只实现了单段，先停下。")
        show("分片信息:", {k: v for k, v in data.items() if k != "part_presigned_urls"})
        print("     你的文件不大（<100MB），正常应该是单段；出现分片可以先检查是不是文件太大。")
        return 3

    # ③ 轮询
    print("  ③ 等待服务器确认…")
    state = None
    for i in range(30):
        time.sleep(2)
        st3, d3 = call("GET", f"/uploads/{up_id}", key)
        state = (d3.get("data", d3) or {}).get("state")
        if state:
            print(f"     第 {i+1} 次: state = {state}")
        if state in ("available", "ready", "complete"):
            break
        if state in ("failed", "error"):
            show("上传失败:", d3)
            return 1
    if state not in ("available", "ready", "complete"):
        print(f"  ✗ 等不到可用状态（最后 state={state}）。第②步可能没成功，重跑一次即可。")
        return 1

    # ④ 变成 mod 文件
    body = {"upload_id": up_id, "mod_id": str(a.mod_id), "name": name,
            "version": a.version, "description": a.desc or name, "file_category": a.category,
            "primary_mod_manager_download": True, "mod_manager_downloads_enabled": True}
    st4, d4 = call("POST", "/mod-files", key, body)
    print(f"  ④ POST /mod-files → HTTP {st4}")
    if st4 in (200, 201):
        print("\n  ✓✓ 上传完成，去 mod 页的 Files 标签下看一眼")
        show("返回:", d4)
        return 0
    show("失败:", d4)
    print("     提示：422 通常是字段问题（mod_id 不是数字 / file_category 取值不对）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
