# 退回"确认能进游戏"的那一版
import os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import native_deploy as nd
src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backup", "works_in_game")
shutil.copy2(os.path.join(src, "regulation.bin"), os.path.join(nd.MOD, "mod", "regulation.bin"))
shutil.copy2(os.path.join(src, "item_dlc02.msgbnd.dcx"), os.path.join(nd.MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx"))
print("已退回可进游戏的版本 ✓")
