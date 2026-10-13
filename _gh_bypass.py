#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绕开本机那个坏掉的加速器，直接用真实 IP 调 GitHub API 建 Release 并上传附件

背景：本机 hosts 把 github.com / api.github.com 指向 127.0.0.1，那里蹲着一个
GitHub 加速器（PID 20316），它现在回 502。直连真实 IP 是通的（HTTP 200/403）。

做法：全程用 curl --resolve 把域名钉到真实 IP，并且 --noproxy '*' 绕开系统代理。
**不改 hosts、不杀进程、不碰系统设置。**

token 从 `gh auth token` 读（只在本机内存里用，绝不打印）。
"""
import json
import os
import subprocess
import time

REPO = "netori/fahun-randomizer"
TAG = "v1.1.0"
TITLE = "v1.1.0 · 法魂职业道具和装备随机器（中文版）"
ZIP = "ConvergenceClassItemRandomizer_v1.1.0.zip"
NOTES = "docs/RELEASE_v1.1.0.md"
API_IPS = ["140.82.113.3", "140.82.112.3", "140.82.113.6", "140.82.114.3"]
UP_IPS = ["140.82.113.3", "140.82.112.3", "140.82.113.6"]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True)
    out = (r.stdout or b"") + (r.stderr or b"")
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return out.decode("gbk", "replace")


def pick_ip(host, ips):
    """挑一个能通的 IP（403/200 都算通，502/超时不算）"""
    for ip in ips:
        code = run(["curl", "-s", "-o", os.devnull, "-w", "%{http_code}", "-m", "10",
                    "--noproxy", "*", "--resolve", f"{host}:443:{ip}", f"https://{host}/"]).strip()
        print(f"    {host} → {ip}: HTTP {code}", flush=True)
        if code in ("200", "403", "301", "302"):
            return ip
    return None


def curl(host, ip, url, token, method="GET", data=None, extra=None, outfile=None):
    cmd = ["curl", "-s", "-m", "120", "--noproxy", "*", "--resolve", f"{host}:443:{ip}",
           "-X", method, "-H", f"Authorization: Bearer {token}",
           "-H", "Accept: application/vnd.github+json"]
    if data is not None:
        cmd += ["-H", "Content-Type: application/json", "--data", data]
    if extra:
        cmd += extra
    cmd.append(url)
    if outfile:
        cmd += ["-o", outfile, "-w", "%{http_code}"]
    return run(cmd)


def main():
    token = run(["gh", "auth", "token"]).strip()
    if not token:
        print("  ✗ 取不到 GitHub token（gh 未登录？）")
        return 1
    print(f"  ✓ 取到 token（长度 {len(token)}，不回显）", flush=True)

    print("\n  ═══ 找可用 IP ═══")
    api_ip = pick_ip("api.github.com", API_IPS)
    up_ip = pick_ip("uploads.github.com", UP_IPS)
    if not api_ip:
        print("  ✗ api.github.com 没有可用 IP")
        return 1
    print(f"  ✓ api={api_ip} ｜ uploads={up_ip or api_ip}")

    # ① 建 release（已存在就跳过）
    print("\n  ═══ ① 检查/创建 Release ═══")
    body = json.dumps({"tag_name": TAG, "name": TITLE,
                       "body": open(NOTES, encoding="utf-8").read()}, ensure_ascii=False)
    r = curl("api.github.com", api_ip, f"https://api.github.com/repos/{REPO}/releases",
             token, "POST", data=body)
    try:
        d = json.loads(r)
    except Exception:
        d = {}
    if d.get("id"):
        rid = d["id"]
        print(f"  ✓ 已创建 v1.1.0（release id {rid}）")
    else:
        msg = (d.get("message") or r[:160]) if isinstance(d, dict) else r[:160]
        print(f"  · 创建返回: {msg}")
        r2 = curl("api.github.com", api_ip, f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}",
                  token)
        d2 = json.loads(r2) if r2.strip().startswith("{") else {}
        rid = d2.get("id")
        if not rid:
            print("  ✗ 拿不到 release id，停止")
            print("   ", r2[:300])
            return 1
        print(f"  ✓ 已存在 v1.1.0（release id {rid}）")

    # ② 上传附件
    print("\n  ═══ ② 上传附件 ═══")
    size = os.path.getsize(ZIP)
    print(f"    {ZIP}  {size/1048576:.2f} MB")
    url = f"https://uploads.github.com/repos/{REPO}/releases/{rid}/assets?name={ZIP}"
    code = curl("uploads.github.com", up_ip or api_ip, url, token, "POST",
                extra=["-H", "Content-Type: application/zip", "--data-binary", f"@{ZIP}"],
                outfile="_asset_resp.json")
    print(f"    HTTP {code.strip()}")
    try:
        a = json.load(open("_asset_resp.json", encoding="utf-8"))
        if a.get("browser_download_url"):
            print(f"  ✓✓ 上传成功：{a['browser_download_url']}  （{a.get('size', 0)/1048576:.2f} MB）")
        else:
            print(f"    {str(a)[:200]}")
    except Exception as e:
        print(f"    ✗ 解析响应失败: {e}")
    if os.path.exists("_asset_resp.json"):
        os.remove("_asset_resp.json")

    # ③ 复核
    print("\n  ═══ ③ 复核 ═══")
    r = curl("api.github.com", api_ip, f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}", token)
    try:
        d = json.loads(r)
        print(f"    tag:  {d['tag_name']}")
        print(f"    标题: {d['name']}")
        print(f"    链接: {d['html_url']}")
        for a in d.get("assets", []):
            print(f"    附件: {a['name']}  {a['size']} 字节  下载 {a['download_count']} 次")
    except Exception as e:
        print(f"    ✗ {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
