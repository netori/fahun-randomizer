# -*- coding: utf-8 -*-
"""退役旧方案层（用户 2026-10-18 明确授权才允许跑）：把这几个「旧双重置换产物」移出 方案\\。

为什么默认不删：方案层是用户磁盘上的产物（`docs/敌人随机_修复_交接提示词.md` 的硬约束）。
用户这次明确说「由你删掉旧层」，所以这里做**可恢复删除**：
  ① 优先用 Windows Shell API 丢进回收站（FOF_ALLOWUNDO）；
  ② 回收站不可用（非交互会话/权限）时，退回到「移到工作区外的退役目录」并打印路径；
任何一步失败都**不会**假装删除成功 —— 最后逐个核对目录是否已不存在。

用法：
    python investigation\\apply\\retire_old_plan_layers.py --list
    python investigation\\apply\\retire_old_plan_layers.py --yes
"""
import argparse
import ctypes
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plan_layer as PL  # noqa: E402

#: 只退役这 5 个（2026-10-17 审计确认的旧层）；脚本不按通配扫描，避免误删新层。
TARGETS = [
    "手动_20261017_000031_敌人+外观",
    "手动_20261016_235559_敌人+外观",
    "手动_20261016_235137_敌人+外观",
    "手动_20261016_233858_敌人+外观",
    "20261016_2325_种子20261010_敌人+说明书",
]

FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p),
                ("wFunc", ctypes.c_uint),
                ("pFrom", ctypes.c_wchar_p),
                ("pTo", ctypes.c_wchar_p),
                ("fFlags", ctypes.c_uint16),
                ("fAnyOperationsAborted", ctypes.c_int),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", ctypes.c_wchar_p)]


def to_recycle_bin(path):
    """Windows Shell 删除（带撤销）。返回 True/False。"""
    try:
        op = SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = os.path.abspath(path) + "\0\0"
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
        r = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))  # noqa
        return r == 0 and not os.path.exists(path)
    except Exception:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="退役旧方案层（可恢复）")
    ap.add_argument("--yes", action="store_true", help="确认执行（不加只列清单）")
    ap.add_argument("--name", action="append", default=[],
                    help="额外要退役的方案层目录名（可多次给；用于退役被新层取代的临时层）")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    pr = PL.plans_root()
    print("方案目录：", pr)
    targets = TARGETS + list(a.name or [])
    gone, failed = [], []
    fallback_dir = os.path.join(os.path.dirname(os.path.dirname(pr)),
                                "_retired_plan_layers_" + time.strftime("%Y%m%d_%H%M%S"))
    for name in targets:
        p = os.path.join(pr, name)
        if not os.path.isdir(p):
            print("  - %-38s 已不存在（跳过）" % name)
            continue
        sz = sum(os.path.getsize(os.path.join(r, f)) for r, _s, fs in os.walk(p) for f in fs)
        if not a.yes:
            print("  - %-38s %.1f MB（未执行；加 --yes 才动）" % (name, sz / 1048576))
            continue
        ok = to_recycle_bin(p)
        how = "回收站"
        if not ok or os.path.exists(p):
            # 退路：移出 方案\ 到工作区**外面**的退役目录（仍可手动找回）
            try:
                os.makedirs(fallback_dir, exist_ok=True)
                shutil.move(p, os.path.join(fallback_dir, name))
                ok = not os.path.exists(p)
                how = "移到 %s" % fallback_dir
            except Exception as e:                                 # noqa: BLE001
                ok = False
                print("  [X] %s 删除失败：%s" % (name, e))
        if ok:
            gone.append(name)
            print("  ✓ %-38s 已退役（%s）" % (name, how))
        else:
            failed.append(name)
            print("  [X] %-38s 仍存在 —— 没删掉" % name)
    if a.yes:
        print("\n退役 %d 个；失败 %d 个" % (len(gone), len(failed)))
        return 0 if not failed else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
