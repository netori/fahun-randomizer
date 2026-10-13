# _patch_modroot5.py — 在任何管线被 import 之前就发布 MOD 路径
import ast
import os

WS = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(WS, "randgui.py")
raw = open(p, encoding="utf-8", newline="").read()
s = raw.replace("\r\n", "\n")
n = 0

# ① cli_deploy：import 管线之前先发布
OLD1 = '''    def cli_deploy(argv):
        """命令行写入：法魂职业道具和装备随机器.exe --deploy <plan.csv> [--no-guide]"""
        sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))'''
NEW1 = '''    def cli_deploy(argv):
        """命令行写入：法魂职业道具和装备随机器.exe --deploy <plan.csv> [--no-guide]"""
        # 必须在 import 管线之前发布 MOD 路径：模块在 import 时就会读它
        publish_mod_root(find_mod_root())
        sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))'''
if OLD1 in s:
    s = s.replace(OLD1, NEW1, 1); n += 1
else:
    print("    ⚠ cli_deploy 未匹配")

# ② main()：进入任何分支之前先发布一次（界面与自检都受益）
OLD2 = '''def main():
    if "--deploy" in sys.argv:'''
NEW2 = '''def main():
    # 尽早发布 MOD 路径：写入管线在 import 时就会读取它（打包版尤其重要）
    try:
        publish_mod_root(find_mod_root())
    except Exception:
        pass
    if "--deploy" in sys.argv:'''
if OLD2 in s:
    s = s.replace(OLD2, NEW2, 1); n += 1
else:
    print("    ⚠ main() 未匹配")

ast.parse(s)
open(p, "w", encoding="utf-8", newline="").write(s.replace("\n", "\r\n") if "\r\n" in raw else s)
print(f"  ✓ randgui.py：{n} 处修改（import 管线前先发布 MOD 路径）")
print(f"    publish_mod_root 出现 {s.count('publish_mod_root')} 处")
