# verify_tree.py — 逐文件比对两棵解包树（往返保真校验 / 打补丁前后校验）
# 用法: python verify_tree.py --a <树A> --b <树B> [--only param|xml] [--json out.json]
import argparse, hashlib, json, os, sys


def sha(p, n=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(n), b""):
            h.update(c)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--only", default="", help="只看 .param 或 .param.xml")
    ap.add_argument("--json", default="")
    ap.add_argument("--max-show", type=int, default=15)
    a = ap.parse_args()
    fa = {f for f in os.listdir(a.a) if os.path.isfile(os.path.join(a.a, f))}
    fb = {f for f in os.listdir(a.b) if os.path.isfile(os.path.join(a.b, f))}
    if a.only:
        suf = ".param" if a.only == "param" else ".param.xml"
        fa = {f for f in fa if f.endswith(suf)}
        fb = {f for f in fb if f.endswith(suf)}
    common = sorted(fa & fb)
    same, diff, size_diff = [], [], []
    for f in common:
        pa, pb = os.path.join(a.a, f), os.path.join(a.b, f)
        sa, sb = os.path.getsize(pa), os.path.getsize(pb)
        if sa != sb:
            size_diff.append({"file": f, "size_a": sa, "size_b": sb})
            continue
        (same if sha(pa) == sha(pb) else diff).append(f)
    print(f"=== 比对 {a.a}  ↔  {a.b} ===")
    print(f"  共同文件 {len(common)} | 完全一致 {len(same)} | 内容不同 {len(diff)} | 大小不同 {len(size_diff)}")
    print(f"  仅 A 有: {sorted(fa - fb)[:8]} | 仅 B 有: {sorted(fb - fa)[:8]}")
    for f in diff[:a.max_show]:
        print(f"    内容不同: {f}")
    for d in size_diff[:a.max_show]:
        print(f"    大小不同: {d['file']}  A={d['size_a']}  B={d['size_b']}")
    if a.json:
        json.dump({"a": a.a, "b": a.b, "common": len(common), "identical": len(same), "content_diff": diff,
                   "size_diff": size_diff, "only_a": sorted(fa - fb), "only_b": sorted(fb - fa)},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  回执 → {a.json}")
    return 0 if not diff and not size_diff and not (fa ^ fb) else 1


if __name__ == "__main__":
    raise SystemExit(main())
