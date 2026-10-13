# _patch_push.py — 给 API 调用加重试 + 每推一个就更新分支（断点续传才真正生效）
import ast
import os

WS = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(WS, "_gh_push2.py")
s = open(p, encoding="utf-8").read()

# ① api() 加三次重试
OLD = '''    out = sh(cmd)
    if tmp and os.path.exists(tmp):
        os.remove(tmp)
    try:
        return json.loads(out), out
    except Exception:
        return None, out'''
NEW = '''    out, d = "", None
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
    return d, out'''
assert OLD in s, "api 函数锚点没匹配"
s = s.replace(OLD, NEW, 1)

# ② 每推完一个提交就更新分支（断点续传的关键）
OLD2 = '''        remote_head = cd["sha"]
        print(f"       ✓ 远端提交 {remote_head[:12]}")'''
NEW2 = '''        remote_head = cd["sha"]
        print(f"       ✓ 远端提交 {remote_head[:12]}")
        # 每推一个就把分支挪过去 —— 这样中途断了也能从断点接着走，不重复推
        rb, _ = api(token, "POST", f"/repos/{REPO}/git/refs",
                    {"ref": f"refs/heads/{BRANCH}", "sha": remote_head})
        if not rb:
            api(token, "PATCH", f"/repos/{REPO}/git/refs/heads/{BRANCH}",
                {"sha": remote_head, "force": True})'''
assert OLD2 in s, "提交锚点没匹配"
s = s.replace(OLD2, NEW2, 1)

ast.parse(s)
open(p, "w", encoding="utf-8").write(s)
print("  ✓ 已加重试（3 次，遇限流等 20 秒）与逐提交更新分支")
