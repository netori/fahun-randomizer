# 只切换说明书：python _deploy_guide.py native|witchy|orig
import os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import native_deploy as nd
A = os.path.dirname(os.path.abspath(__file__))
tgt = os.path.join(nd.MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
mode = (sys.argv[1] if len(sys.argv) > 1 else "native").lower()
src = {"native": os.path.join(A, "backup", "broken_native", "item_dlc02.msgbnd.dcx"),
       "witchy": os.path.join(A, "backup", "works_in_game", "item_dlc02.msgbnd.dcx"),
       "orig": nd.find_original("item_dlc02.msgbnd.dcx.zhocn.orig_*")}[mode]
shutil.copy2(src, tgt)
print(f"说明书已切换为 {mode}: {os.path.getsize(tgt)} B")
