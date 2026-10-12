# _patch_relocate.py — 让 relocate() 把「所有会写文件的路径」都重定位到释放出来的工作区
import ast
import os

WS = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(WS, "investigation", "apply", "native_deploy.py")
raw = open(p, encoding="utf-8", newline="").read()
s = raw.replace("\r\n", "\n")

OLD = '''    def relocate(ws=None):
        """把各模块的路径常量改到真实工作区（打包成 exe 后 __file__ 指向临时目录，必须重定位）"""
        ws = ws or workspace_of()
        if not ws:
            raise FileNotFoundError("找不到工作区（请把 exe 放在 随机mod 目录下运行）")
        apply_dir = os.path.join(ws, "investigation", "apply")
        root = ws
        targets = {
            "native_guide": {"APPLY": apply_dir, "MOD": MOD},
            "native_apply": {"APPLY": apply_dir, "ROOT": root, "MOD": MOD},
            "erio": {"APPLY": apply_dir},
            "fix_guide": {"APPLY": apply_dir, "ROOT": root,
                          "CAT": os.path.join(root, "investigation", "randomization-catalog"),
                          "WB": os.path.join(root, "investigation", "weapon-baseline")},
        }
        for name, consts in targets.items():
            m = sys.modules.get(name)
            if m:
                for k, v in consts.items():
                    setattr(m, k, v)
        globals()["WS"] = ws
        return ws'''

NEW = '''    def relocate(ws=None):
        """把所有「路径常量」改到真正的工作区。

        打包成 exe 后 __file__ 指向临时解包目录，而真正的文件在 exe 旁边那份工作区里，
        所以每一个会读/写文件的常量都必须重定位 —— 漏一个就会去解包目录里找备份，
        表现是「系统找不到指定的路径」。这里把**本模块自己**也算进去（它管着备份目录）。

        同时在这里重新确定 MOD：界面/命令行把结果放进 CONVERGENCE_MOD_ROOT，
        但模块往往在界面解析之前就被 import 了，必须等到"真正要写入"这一刻再读一次。
        """
        _env = os.environ.get("CONVERGENCE_MOD_ROOT")
        if _env and os.path.isdir(os.path.join(_env, "mod")):
            globals()["MOD"] = os.path.normpath(_env)
        elif not os.path.isdir(os.path.join(globals().get("MOD") or "", "mod")):
            _base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
            for _c in (_base, os.path.dirname(_base)):
                if os.path.isfile(os.path.join(_c, "mod", "regulation.bin")):
                    globals()["MOD"] = os.path.normpath(_c)
                    break
        mod_now = globals().get("MOD")
        ws = ws or workspace_of()
        if not ws:
            raise FileNotFoundError("找不到工作区（请把 exe 放在 随机mod 目录下运行）")
        apply_dir = os.path.join(ws, "investigation", "apply")
        root = ws
        common = {"APPLY": apply_dir, "ROOT": root, "MOD": mod_now}
        targets = {
            # 本模块自己：APPLY 决定备份目录，LOG 决定收据目录
            "native_deploy": dict(common, WS=ws, LOG=os.path.join(apply_dir, "logs"),
                                  CAT=os.path.join(root, "investigation", "randomization-catalog-review")),
            "native_guide": dict(common),
            "native_apply": dict(common),
            "erio": {"APPLY": apply_dir},
            "_guide_rebuild": {"APPLY": apply_dir},
            "_guide_fit": {"APPLY": apply_dir},
            "_guide_audit": {"APPLY": apply_dir},
            "fix_guide": dict(common,
                              CAT=os.path.join(root, "investigation", "randomization-catalog"),
                              WB=os.path.join(root, "investigation", "weapon-baseline")),
        }
        for name, consts in targets.items():
            m = sys.modules.get(name)
            if m:
                for k, v in consts.items():
                    setattr(m, k, v)
        globals()["WS"] = ws
        # 备份/日志/中介目录必须真实存在，否则第一步就写不进去
        for d in ("backup", "logs", "out", "work/msg/zh"):
            os.makedirs(os.path.join(apply_dir, d), exist_ok=True)
        return ws'''

if OLD not in s:
    print("  ✗ 未匹配到 relocate 原文，未改动")
    raise SystemExit(1)
s = s.replace(OLD, NEW, 1)
ast.parse(s)
open(p, "w", encoding="utf-8", newline="").write(s.replace("\n", "\r\n"))
print("  ✓ relocate() 已重写：补上 native_deploy / _guide_rebuild / _guide_fit / _guide_audit")
print("    并加入 MOD 运行时重解析 + 四类目录的自动创建")

s2 = open(p, encoding="utf-8").read()
for key in ("native_deploy", "_guide_rebuild", "_guide_audit", "CONVERGENCE_MOD_ROOT", "work/msg/zh"):
    print(f"    {key:<22} {s2.count(key)} 处")
