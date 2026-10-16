# -*- coding: utf-8 -*-
"""把"真·换敌人"的样张部署进法魂 MOD（带备份），或一键回滚。

用法（默认是**只看不动**的 dry-run）：
    python _deploy_msb_test.py            # 只打印会做什么、比对哈希，不写任何文件
    python _deploy_msb_test.py --apply    # 备份原图 → 覆盖成样张
    python _deploy_msb_test.py --revert   # 从备份还原

样张是什么：`msb_write_probe/m10_00_00_00_swapped.msb.dcx` —— 法魂 Limgrave（m10_00_00_00）
里两个敌人的 npc_id / think_id / chara_id / 模型索引**整组对调**（实测：283 个 part 里只有这 2 个变了）。
它是用 `msb_write.patch` 只改定点 int32 生成的，没有增删任何条目。

风险与回滚：原图会被复制成 `.bak_msbtest_<时间戳>` 放在同目录；`--revert` 自动找最新的那份还原。
想手工回滚也一样：把 `.bak_msbtest_*` 复制回去覆盖 `m10_00_00_00.msb.dcx` 即可。
"""
import hashlib
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "apply"))

import enemy_randomizer as ER          # noqa: E402

MAP_NAME = "m10_00_00_00.msb.dcx"
MOD = os.path.dirname(os.path.dirname(os.path.abspath(ER._mod_reg())))
TARGET = os.path.join(MOD, "mod", "map", "MapStudio", MAP_NAME)
SAMPLE = os.path.join(HERE, "msb_write_probe", "m10_00_00_00_swapped.msb.dcx")


def h(p, n=16):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:n] if os.path.isfile(p) else "（文件不存在）"


def find_backups():
    d = os.path.dirname(TARGET)
    base = MAP_NAME + ".bak_msbtest_"
    return sorted((os.path.join(d, f) for f in os.listdir(d) if f.startswith(base)), reverse=True)


def main(argv):
    apply_it = "--apply" in argv
    revert = "--revert" in argv
    print("目标地图:", TARGET)
    print("当前哈希:", h(TARGET), "｜大小:", os.path.getsize(TARGET) if os.path.isfile(TARGET) else "-")
    print("样张    :", SAMPLE)
    print("样张哈希:", h(SAMPLE), "｜大小:", os.path.getsize(SAMPLE) if os.path.isfile(SAMPLE) else "-")

    if revert:
        baks = find_backups()
        if not baks:
            print("\n没找到备份（%s.bak_msbtest_*），不动作。" % MAP_NAME)
            return 1
        print("\n用这份备份还原:", baks[0])
        shutil.copy2(baks[0], TARGET)
        print("已还原。当前哈希:", h(TARGET))
        return 0

    if not os.path.isfile(SAMPLE):
        print("\n样张不存在，先跑生成它的命令。")
        return 1
    if h(TARGET) == h(SAMPLE):
        print("\n目标已经是样张内容了，不用再写。")
        return 0

    if not apply_it:
        print("\n[dry-run] 会做这些事：")
        print("  ① 把当前图备份成 %s.bak_msbtest_%s" % (MAP_NAME, time.strftime("%Y%m%d_%H%M%S")))
        print("  ② 用样张覆盖它")
        print("  ③ 想还原：python _deploy_msb_test.py --revert")
        print("\n确认要写就加 --apply。")
        return 0

    bak = "%s.bak_msbtest_%s" % (TARGET, time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(TARGET, bak)
    shutil.copy2(SAMPLE, TARGET)
    print("\n已部署：备份 →", bak)
    print("现在哈希:", h(TARGET), "（样张是", h(SAMPLE), "）")
    print("\n进游戏去 Limgrave（宁姆格福）走一圈：那两只敌人会互换外观与数值。")
    print("要还原：python _deploy_msb_test.py --revert")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
