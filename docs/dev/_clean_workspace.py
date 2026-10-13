# _clean_workspace.py — 工作区清理（默认空跑，加 --apply 才真删）
#   铁律：原始备份与说明书基准是工具运行必需的，任何情况下都不删。
import os, shutil, sys, time, glob

WS = os.path.dirname(os.path.abspath(__file__))
APPLY = os.path.join(WS, "investigation", "apply")
KEEP_FILES = {
    # 说明书基准（必需）
    os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.fmg.xml"),
}
# ⚠️ work/msg/ 整块保留：fix_guide 还要从这里读 PlaceName*.fmg.xml（地点词典）
#    整个目录只有几十 MB，而少一个文件就会让说明书改地点失效 —— 不值得冒险
KEEP_DIRS = {
    os.path.join(APPLY, "work", "msg"),
}
KEEP_PATTERNS = [
    os.path.join(APPLY, "backup", "*.orig_*"),                          # 原始备份（必需）
]


def protected(p):
    ap = os.path.abspath(p)
    for d in KEEP_DIRS:
        if ap == os.path.abspath(d) or ap.startswith(os.path.abspath(d) + os.sep):
            return True
    if ap in KEEP_FILES:
        return True
    for pat in KEEP_PATTERNS:
        if glob.fnmatch.fnmatch(os.path.abspath(p), pat):
            return True
    return False


def dir_size(p):
    t = 0
    for dp, dn, fn in os.walk(p):
        for f in fn:
            try:
                t += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return t


def plan():
    """返回 [(路径, 类型, 大小)]"""
    items = []

    # ① 旧的打包产物（保留最新一个 dist*）
    dists = sorted(glob.glob(os.path.join(WS, "dist*")),
                   key=lambda p: (os.path.getmtime(p) if os.path.exists(p) else 0))
    for d in dists[:-1]:
        items.append((d, "旧打包产物", dir_size(d)))
    for name in ("build_native", "build"):
        d = os.path.join(WS, name)
        if os.path.isdir(d):
            items.append((d, "打包中间目录", dir_size(d)))

    # ② 第三方工具（解压版 + 压缩包；都在 .gitignore 里，随时可重新下载）
    for d in glob.glob(os.path.join(WS, "WitchyBND-*.zip")) + [os.path.join(APPLY, "tools")]:
        if os.path.exists(d):
            items.append((d, "第三方工具（可从网上下回）", dir_size(d) if os.path.isdir(d) else os.path.getsize(d)))

    # ③ 早期实验目录（证据都是解包出来的游戏数据）
    d = os.path.join(WS, "investigation", "weapon-baseline")
    if os.path.isdir(d):
        items.append((d, "早期实验（含解包游戏数据）", dir_size(d)))

    # ④ 写入中间产物（**保留说明书基准**）
    w = os.path.join(APPLY, "work")
    if os.path.isdir(w):
        for dp, dn, fn in os.walk(w):
            for f in fn:
                p = os.path.join(dp, f)
                if not protected(p):
                    items.append((p, "写入中间产物", os.path.getsize(p)))

    # ⑤ 旧部署快照（**保留 *.orig_***）
    b = os.path.join(APPLY, "backup")
    if os.path.isdir(b):
        for dp, dn, fn in os.walk(b):
            for f in fn:
                p = os.path.join(dp, f)
                if not protected(p):
                    items.append((p, "旧部署快照", os.path.getsize(p)))
        for name in os.listdir(b):
            p = os.path.join(b, name)
            if os.path.isdir(p) and not protected(p) and dir_size(p) == 0:
                items.append((p, "空目录", 0))

    # ⑥ 旧计划表（可由种子重新生成）
    for f in glob.glob(os.path.join(APPLY, "out", "*.csv")):
        n = os.path.basename(f)
        if n.startswith(("boot_", "bis_", "bisect_")):
            items.append((f, "旧计划表（可重新生成）", os.path.getsize(f)))

    # ⑦ 旧日志（保留最近 5 个）
    lg = os.path.join(APPLY, "logs")
    if os.path.isdir(lg):
        files = [os.path.join(lg, f) for f in os.listdir(lg) if os.path.isfile(os.path.join(lg, f))]
        files.sort(key=os.path.getmtime, reverse=True)
        for f in files[5:]:
            items.append((f, "旧日志", os.path.getsize(f)))

    # ⑧ __pycache__ 与临时文件
    for dp, dn, fn in os.walk(WS):
        if ".git" in dp:
            continue
        for name in list(dn):
            if name == "__pycache__":
                p = os.path.join(dp, name)
                if not protected(p):
                    items.append((p, "__pycache__", dir_size(p)))
        for f in fn:
            if f.endswith((".pyc", ".tmp", ".bak")) or f.startswith("_mut"):
                p = os.path.join(dp, f)
                if not protected(p):
                    items.append((p, "临时文件", os.path.getsize(p)))
    return items


def main():
    apply = "--apply" in sys.argv
    items = plan()
    items.sort(key=lambda x: -x[2])
    tot = sum(i[2] for i in items)
    print(f"  ═══ 清理计划（{'真删' if apply else '空跑'}）═══")
    print(f"  共 {len(items)} 项，合计 {tot/1048576:.1f} MB\n")
    by_kind = {}
    for p, kind, s in items:
        by_kind.setdefault(kind, [0, 0])
        by_kind[kind][0] += 1
        by_kind[kind][1] += s
    for kind, (n, s) in sorted(by_kind.items(), key=lambda x: -x[1][1]):
        print(f"    {s/1048576:>9.1f} MB  {kind}（{n} 项）")
    print("\n  体积最大的 8 项:")
    for p, kind, s in items[:8]:
        print(f"    {s/1048576:>9.1f} MB  {os.path.relpath(p, WS)[:76]}")

    # 红线自检
    print("\n  ═══ 红线自检 ═══")
    bad = [p for p, _k, _s in items if protected(p)]
    for f in ("investigation/apply/work/msg/zh/GoodsCaption.fmg.xml",
              "investigation/apply/backup/regulation.bin.orig_20261011_080825",
              "investigation/apply/backup/item_dlc02.msgbnd.dcx.zhocn.orig_20261011_095021"):
        fp = os.path.join(WS, f)
        mark = "✗ 在删除名单里！" if any(os.path.abspath(x) == os.path.abspath(fp) for x, _k, _s in items) else "✓ 不动"
        print(f"    {mark}  {f}")
    if bad:
        print(f"  ✗ 有 {len(bad)} 个受保护文件被列入删除，已终止")
        return 1

    if not apply:
        print("\n  这是空跑。确认无误后加 --apply 执行。")
        return 0

    done = freed = 0
    for p, kind, s in items:
        if protected(p):
            continue
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
            done += 1
            freed += s
        except OSError as e:
            print(f"    跳过 {os.path.relpath(p, WS)}：{e}")
    print(f"\n  ✓ 已删除 {done} 项，释放 {freed/1048576:.1f} MB")

    print("\n  ═══ 删除后核对 ═══")
    for f in ("investigation/apply/work/msg/zh/GoodsCaption.fmg.xml",
              "investigation/apply/backup/regulation.bin.orig_20261011_080825",
              "investigation/apply/backup/item_dlc02.msgbnd.dcx.zhocn.orig_20261011_095021",
              "investigation/randomization-catalog", "investigation/randomization-dryrun/scripts/randomizer.py",
              "ConvergenceClassItemRandomizer.exe", "randgui.py"):
        fp = os.path.join(WS, f)
        print(f"    {'✓ 在' if os.path.exists(fp) else '✗ 没了！'}  {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
