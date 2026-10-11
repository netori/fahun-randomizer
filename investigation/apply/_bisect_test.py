# _bisect_test.py — 二分定位：哪一份文件让游戏进不去
#   用法：python _bisect_test.py A   → 原始 regulation + 我改的说明书（测说明书）
#         python _bisect_test.py B   → 我改的 regulation + 原始说明书（测 regulation）
#         python _bisect_test.py off → 恢复全原始
import glob, os, shutil, sys

APPLY = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APPLY)
import native_deploy as nd

MOD = nd.MOD
REG = os.path.join(MOD, "mod", "regulation.bin")
MSG = os.path.join(MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
P_REG = nd.find_original("regulation.bin.orig_*")
P_MSG = nd.find_original("item_dlc02.msgbnd.dcx.zhocn.orig_*")
B_REG = os.path.join(APPLY, "backup", "broken_native", "regulation.bin")          # 我的原生 regulation
B_MSG = os.path.join(APPLY, "backup", "broken_native", "item_dlc02.msgbnd.dcx")   # 我的原生说明书


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "off").upper()
    if mode == "A":
        shutil.copy2(P_REG, REG); shutil.copy2(B_MSG, MSG)
        print("已应用 A：原始 regulation + 我的说明书（若进不去 → 说明书是元凶）")
    elif mode == "B":
        shutil.copy2(B_REG, REG); shutil.copy2(P_MSG, MSG)
        print("已应用 B：我的 regulation + 原始说明书（若进不去 → regulation 是元凶）")
    else:
        shutil.copy2(P_REG, REG); shutil.copy2(P_MSG, MSG)
        print("已恢复全原始")
    for p, nm in ((REG, "regulation.bin"), (MSG, "item_dlc02.msgbnd.dcx")):
        print(f"   {nm}: {os.path.getsize(p)} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
