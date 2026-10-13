#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绕开坏掉的加速器，用 GitHub 的 Git Data API 把本地提交推上去（保留完整历史）

为什么不用 git push：本机 DNS + hosts 都被那个加速器接管（github.com → 127.0.0.1），
git 走到那儿就 502。而直接对 api.github.com 用真实 IP 是通的。

安全做法（不直接动 main）：
  ① 先把这些提交推到一个临时分支 push-via-api
  ② 再读回来核对 SHA 与树一致
  ③ 一致了才把 main 快进过去

token 从 `gh auth token` 读，只在本机内存里用，绝不打印。
"""
import json
import os
import subprocess
import sys
import time

REPO = "netori/fahun-randomizer"
IP = "140.82.113.3"
BRANCH = "push-via-api"


def sh(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, cwd=cwd)
    out = (r.stdout or b"") + (r.stderr or b"")
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return out.decode("gbk", "replace")


def api(token, method, path, payload=None, ip=IP, host="api.github.com"):
    cmd = ["curl", "-s", "-m", "180", "--noproxy", "*", "--resolve", f"{host}:443:{ip}",
           "-X", method, "-H", f"Authorization: Bearer {token}",
           "-H", "Accept: application/vnd.github+json",
           "-H", "Content-Type: application/json",
           f"https://{host}{path}"]
    tmp = None
    if payload is not None:
        tmp = f"_api_{int(time.time()*1000)}.json"
        open(tmp, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False))
        cmd += ["--data-binary", f"@{tmp}"]
    out = sh(cmd)
    if tmp and os.path.exists(tmp):
        os.remove(tmp)
    try:
        return json.loads(out), out
    except Exception:
        return None, out


def main():
    token = sh(["gh", "auth", "token"]).strip()
    if not token:
        print("  ✗ 取不到 token")
        return 1
    print(f"  ✓ token 就绪（长度 {len(token)}）")

    # 远端当前的 main
    d, raw = api(token, "GET", f"/repos/{REPO}/git/ref/heads/main")
    if not d or "object" not in d:
        print(f"  ✗ 读不到远端 main: {raw[:160]}")
        return 1
    remote_main = d["object"]["sha"]
    print(f"  远端 main: {remote_main[:12]}")

    # 本地要推的提交（远端之后的）
    log = sh(["git", "log", "--reverse", "--format=%H|%P|%an|%ae|%at|%s",
              f"{remote_main}..HEAD"]).strip().splitlines()
    if not log:
        print("  · 没有要推的提交")
        return 0
    print(f"  要推 {len(log)} 个提交")

    # 本地 > 远端 的每个提交：建 blob / tree / commit
    remote_head = remote_main
    for i, line in enumerate(log, 1):
        sha, parents, an, ae, at, subject = line.split("|", 5)
        print(f"\n  [{i}/{len(log)}] {subject[:52]}")
        # 该提交涉及的文件（相对父提交）
        parent = parents.split()[0] if parents.split() else remote_head
        diff = sh(["git", "diff", "--name-status", f"{parent}", f"{sha}"]).strip().splitlines()
        tree_items = []
        for ln in diff:
            parts = ln.split("\t")
            status, path = parts[0], parts[-1]
            if status.startswith("D"):
                tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
                print(f"       删除 {path}")
                continue
            blob = sh(["git", "cat-file", "-p", f"{sha}:{path}"])
            b = subprocess.run(["git", "cat-file", "-p", f"{sha}:{path}"], capture_output=True)
            content = b.stdout
            import base64
            bd, braw = api(token, "POST", f"/repos/{REPO}/git/blobs",
                           {"content": base64.b64encode(content).decode(), "encoding": "base64"})
            if not bd or "sha" not in bd:
                print(f"       ✗ blob 失败 {path}: {braw[:120]}")
                return 1
            mode = sh(["git", "ls-tree", f"{sha}", path]).split()[0] if sh(["git", "ls-tree", f"{sha}", path]).strip() else "100644"
            tree_items.append({"path": path, "mode": mode if mode in ("100644", "100755") else "100644",
                               "type": "blob", "sha": bd["sha"]})
        td, traw = api(token, "POST", f"/repos/{REPO}/git/trees",
                       {"base_tree": sh(["git", "rev-parse", f"{remote_head}^{{tree}}"]).strip()
                        if i == 1 else None,
                        "tree": tree_items} if i > 1 else {"tree": tree_items})
        if not td or "sha" not in td:
            print(f"       ✗ tree 失败: {traw[:140]}")
            return 1
        cd, craw = api(token, "POST", f"/repos/{REPO}/git/commits",
                       {"message": subject, "tree": td["sha"], "parents": [remote_head],
                        "author": {"name": an, "email": ae, "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(at)))},
                        "committer": {"name": an, "email": ae, "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(at)))}})
        if not cd or "sha" not in cd:
            print(f"       ✗ commit 失败: {craw[:140]}")
            return 1
        remote_head = cd["sha"]
        print(f"       ✓ 远端提交 {remote_head[:12]}")

    # 建/更新临时分支
    print(f"\n  ═══ 更新分支 {BRANCH} ═══")
    rd, raw = api(token, "POST", f"/repos/{REPO}/git/refs",
                  {"ref": f"refs/heads/{BRANCH}", "sha": remote_head})
    if not rd or "object" not in rd:
        rd2, raw2 = api(token, "PATCH", f"/repos/{REPO}/git/refs/heads/{BRANCH}",
                        {"sha": remote_head, "force": True})
        if not rd2:
            print(f"  ✗ 分支更新失败: {raw[:120]} / {raw2[:120]}")
            return 1
    print(f"  ✓ 分支 {BRANCH} → {remote_head[:12]}")

    # 核对
    d, _ = api(token, "GET", f"/repos/{REPO}/git/ref/heads/{BRANCH}")
    got = d["object"]["sha"] if d and "object" in d else None
    local_head = sh(["git", "rev-parse", "HEAD"]).strip()
    print(f"\n  ═══ 核对 ═══")
    print(f"    本地 HEAD      : {local_head[:12]}")
    print(f"    远端分支       : {str(got)[:12]}")
    same_tree = sh(["git", "rev-parse", f"{local_head}^{{tree}}"]).strip() == \
        (api(token, "GET", f"/repos/{REPO}/git/commits/{got}")[0] or {}).get("tree", {}).get("sha")
    print(f"    内容（树）一致 : {'✓' if same_tree else '✗'}")
    print(f"\n  下一步：确认无误后，把 main 指到 {str(got)[:12]}")
    print(f"    （我没有自动动 main —— 等你核对完再说）")
    print(f"\n  预览地址：https://github.com/{REPO}/tree/{BRANCH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
