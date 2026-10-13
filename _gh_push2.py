#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本地未推的提交经 Git Data API 推上去（保留完整历史）—— 修正版

上一版的两个问题：
  1. 漏了 base_tree ⇒ 新树里只有改动的文件，等于把其它文件全删了。
     GitHub 直接拒了（GitRPC::BadObjectState）—— 这个拒绝是对的保护。
  2. 新提交只存在于远端，本地 rev-parse 不到它的树，所以 base_tree 必须从 API 取。
   同时加了断点续传：已经推上去的那两个不重复推。

仍然不直接动 main：先推临时分支，核对树一致后再决定。
"""
import base64
import json
import os
import subprocess
import sys
import time

REPO = "netori/fahun-randomizer"
IP = "140.82.113.3"
BRANCH = "push-via-api"


def unq(p):
    """git 若还是给了带引号/反斜杠的路径，这里还原成真正的文件名（双保险）"""
    if len(p) >= 2 and p[0] == '"' and p[-1] == '"':
        body = p[1:-1]
        try:
            return body.encode("latin-1", "backslashreplace").decode("unicode_escape").encode("latin-1").decode("utf-8")
        except Exception:
            return body
    return p


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True)
    out = (r.stdout or b"") + (r.stderr or b"")
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return out.decode("gbk", "replace")


def raw(cmd):
    return subprocess.run(cmd, capture_output=True).stdout


def api(token, method, path, payload=None):
    cmd = ["curl", "-s", "-m", "180", "--noproxy", "*", "--resolve", f"api.github.com:443:{IP}",
           "-X", method, "-H", f"Authorization: Bearer {token}",
           "-H", "Accept: application/vnd.github+json",
           "-H", "Content-Type: application/json",
           f"https://api.github.com{path}"]
    tmp = None
    if payload is not None:
        tmp = f"_api_{os.getpid()}_{int(time.time()*1000)}.json"
        open(tmp, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False))
        cmd += ["--data-binary", f"@{tmp}"]
    out, d = "", None
    for attempt in range(3):                     # 网络抖一下就重试，别一次失败就前功尽弃
        out = sh(cmd)
        try:
            d = json.loads(out)
        except Exception:
            d = None
        if isinstance(d, dict) and (d.get("sha") or d.get("object") or d.get("id") is not None):
            break
        if isinstance(d, dict) and d.get("message") and "rate limit" in str(d["message"]).lower():
            print("       （限流，等 20 秒）", flush=True)
            time.sleep(20)
            continue
        time.sleep(3)
    if tmp and os.path.exists(tmp):
        os.remove(tmp)
    return d, out


def tree_of(token, sha):
    d, _ = api(token, "GET", f"/repos/{REPO}/git/commits/{sha}")
    return (d or {}).get("tree", {}).get("sha")


def main():
    token = sh(["gh", "auth", "token"]).strip()
    if not token:
        print("  ✗ 取不到 token")
        return 1

    rmain, _ = api(token, "GET", f"/repos/{REPO}/git/ref/heads/main")
    remote_main = (rmain or {}).get("object", {}).get("sha")
    print(f"  远端 main: {str(remote_main)[:12]}")

    # 断点：临时分支已经推到哪了
    rbr, _ = api(token, "GET", f"/repos/{REPO}/git/ref/heads/{BRANCH}")
    remote_head = (rbr or {}).get("object", {}).get("sha") or remote_main
    print(f"  已推到的位置（{BRANCH}）: {remote_head[:12]}")

    local_head = sh(["git", "rev-parse", "HEAD"]).strip()
    local_tree = sh(["git", "rev-parse", f"{local_head}^{{tree}}"]).strip()
    if tree_of(token, remote_head) == local_tree:
        print("  ✓ 远端分支的树已经和本地 HEAD 一致 —— 无需再推")
        print(f"  预览：https://github.com/{REPO}/tree/{BRANCH}")
        return 0

    # 找出还没推的本地提交：从远端已推位置对应的那个本地提交之后开始
    allc = sh(["git", "log", "--reverse", "--format=%H", f"{remote_main}..HEAD"]).strip().splitlines()
    # 定位已推到的那个本地提交（比对树）
    start = 0
    for i, c in enumerate(allc):
        if sh(["git", "rev-parse", f"{c}^{{tree}}"]).strip() == tree_of(token, remote_head):
            start = i + 1
            break
    todo = allc[start:]
    print(f"  还要推 {len(todo)} 个提交")

    for i, sha in enumerate(todo, 1):
        subject = sh(["git", "log", "-1", "--format=%s", sha]).strip()
        an = sh(["git", "log", "-1", "--format=%an", sha]).strip()
        ae = sh(["git", "log", "-1", "--format=%ae", sha]).strip()
        at = sh(["git", "log", "-1", "--format=%at", sha]).strip()
        parent_local = sh(["git", "log", "-1", "--format=%P", sha]).split()
        parent = parent_local[0] if parent_local else remote_main
        base_tree = tree_of(token, remote_head)          # ← 关键修正：从 API 取父提交的树
        print(f"\n  [{i}/{len(todo)}] {subject[:52]}")

        diff = sh(["git", "-c", "core.quotepath=false", "diff", "--name-status", parent, sha]).strip().splitlines()
        tree_items = []
        for ln in diff:
            parts = ln.split("\t")
            status, path = parts[0], unq(parts[-1])
            if status.startswith("D"):
                tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
                print(f"       删除 {path}")
                continue
            content = raw(["git", "cat-file", "-p", f"{sha}:{path}"])
            bd, braw = api(token, "POST", f"/repos/{REPO}/git/blobs",
                           {"content": base64.b64encode(content).decode(), "encoding": "base64"})
            if not bd or "sha" not in bd:
                print(f"       ✗ blob 失败 {path}: {str(braw)[:110]}")
                return 1
            mt = sh(["git", "-c", "core.quotepath=false", "ls-tree", sha, "--", path]).split()
            mode = mt[0] if mt and mt[0] in ("100644", "100755") else "100644"
            tree_items.append({"path": path, "mode": mode, "type": "blob", "sha": bd["sha"]})

        td, traw = api(token, "POST", f"/repos/{REPO}/git/trees",
                       {"base_tree": base_tree, "tree": tree_items})
        if not td or "sha" not in td:
            print(f"       ✗ tree 失败: {str(traw)[:130]}")
            return 1
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(at)))
        cd, craw = api(token, "POST", f"/repos/{REPO}/git/commits",
                       {"message": subject, "tree": td["sha"], "parents": [remote_head],
                        "author": {"name": an, "email": ae, "date": stamp},
                        "committer": {"name": an, "email": ae, "date": stamp}})
        if not cd or "sha" not in cd:
            print(f"       ✗ commit 失败: {str(craw)[:130]}")
            return 1
        remote_head = cd["sha"]
        print(f"       ✓ 远端提交 {remote_head[:12]}")
        # 每推一个就把分支挪过去 —— 这样中途断了也能从断点接着走，不重复推
        rb, _ = api(token, "POST", f"/repos/{REPO}/git/refs",
                    {"ref": f"refs/heads/{BRANCH}", "sha": remote_head})
        if not rb:
            api(token, "PATCH", f"/repos/{REPO}/git/refs/heads/{BRANCH}",
                {"sha": remote_head, "force": True})

    # 更新临时分支
    rd, _ = api(token, "POST", f"/repos/{REPO}/git/refs",
                {"ref": f"refs/heads/{BRANCH}", "sha": remote_head})
    if not rd:
        api(token, "PATCH", f"/repos/{REPO}/git/refs/heads/{BRANCH}",
            {"sha": remote_head, "force": True})

    print(f"\n  ═══ 核对 ═══")
    print(f"    本地 HEAD 树 : {local_tree}")
    print(f"    远端分支树   : {tree_of(token, remote_head)}")
    ok = tree_of(token, remote_head) == local_tree
    print(f"    一致         : {'✓✓ 完全一致' if ok else '✗ 不一致'}")
    print(f"    远端分支头   : {remote_head[:12]}")
    print(f"\n  预览：https://github.com/{REPO}/tree/{BRANCH}")
    print(f"  确认无误后把 main 指过去（我没有自动动 main）：")
    print(f"    curl -X PATCH ... /git/refs/heads/main  sha={remote_head}")
    with open(".push_result.txt", "w", encoding="utf-8") as f:
        f.write(f"{remote_head}\n{local_tree}\n{'ok' if ok else 'bad'}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
