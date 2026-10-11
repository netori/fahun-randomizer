# deploy.py — 把重打包好的 regulation.bin 部署进 MOD（写前自动再备份一次）
# rollback.py 的反向操作见 --rollback。
import argparse, hashlib, json, os, shutil, sys, time

APPLY = os.path.dirname(os.path.abspath(__file__))                       # 随机mod/investigation/apply
ROOT = os.path.dirname(os.path.dirname(APPLY))                         # 随机mod
MOD = os.path.join(os.path.dirname(ROOT), "法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）")
TARGET = os.path.join(MOD, "mod", "regulation.bin")


def sha(p, n=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(n), b""):
            h.update(c)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", default=os.path.join(APPLY, "out", "regulation.bin"), help="新的 regulation.bin")
    ap.add_argument("--rollback", metavar="BACKUP", help="用某个备份还原")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    ts = time.strftime("%Y%m%d_%H%M%S")
    if a.rollback:
        src = a.rollback
        if not os.path.exists(src):
            sys.exit(f"备份不存在: {src}")
        cur = os.path.join(APPLY, "backup", f"regulation.bin.before_rollback_{ts}")
        shutil.copy2(TARGET, cur)
        shutil.copy2(src, TARGET)
        print(f"已回滚: {src} → {TARGET}")
        print(f"  回滚前的文件另存: {cur}")
        print(f"  现在 MOD 里的 sha256: {sha(TARGET)[:24]}…")
        json.dump({"action": "rollback", "timestamp": ts, "restored_from": src, "saved_before": cur,
                   "target_sha256": sha(TARGET)}, open(os.path.join(APPLY, "backup", f"rollback_{ts}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        return 0
    if not os.path.exists(a.new):
        sys.exit(f"找不到新文件: {a.new}")
    old_hash = sha(TARGET) if os.path.exists(TARGET) else ""
    new_hash = sha(a.new)
    print("=== 部署 regulation.bin ===")
    print(f"  当前 MOD: {TARGET}")
    print(f"    sha256 {old_hash[:32]}…  ({os.path.getsize(TARGET) if os.path.exists(TARGET) else 0} B)")
    print(f"  新文件:   {a.new}")
    print(f"    sha256 {new_hash[:32]}…  ({os.path.getsize(a.new)} B)")
    if old_hash == new_hash:
        print("  两者相同，无需部署。")
        return 0
    if not a.yes:
        print("  未加 --yes，未做任何写入。")
        return 1
    # 1) 先在 investigation 里留一份"部署前"快照
    pre = os.path.join(APPLY, "backup", f"regulation.bin.before_deploy_{ts}")
    shutil.copy2(TARGET, pre)
    # 2) 再在 MOD 里留一份就地备份（便于手改回去）
    inplace = os.path.join(MOD, "mod", f"regulation.bin.bak_{ts}")
    shutil.copy2(TARGET, inplace)
    # 3) 部署
    shutil.copy2(a.new, TARGET)
    rec = {"action": "deploy", "timestamp": ts, "target": TARGET, "new_source": a.new,
           "old_sha256": old_hash, "new_sha256": sha(TARGET), "pre_deploy_backup": pre, "inplace_backup": inplace}
    json.dump(rec, open(os.path.join(APPLY, "backup", f"deploy_{ts}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  ✅ 已部署。部署前快照: {pre}")
    print(f"     就地备份: {inplace}")
    print(f"     部署后 sha256: {rec['new_sha256'][:32]}…")
    print("  回滚：python investigation/apply/deploy.py --rollback <上面的备份路径> --yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
