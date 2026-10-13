# _bundle_stub.py — 仅供 PyInstaller 分析依赖用，不参与运行
#
# 为什么需要它：写入管线这些模块是「运行时」从磁盘加载的（sys.path 动态插入），
# PyInstaller 静态分析 randgui.py 时看不到它们，于是 html / xml / struct 这类
# 只被管线用到的标准库不会被收进 exe，玩家那边一写入就 ModuleNotFoundError。
# 这里把它们显式 import 一遍，让打包器把依赖收全。
import erio, param_layout, param_patch, fmg, oodle                      # noqa
import planlib  # noqa
import native_apply, native_deploy, native_guide, fix_guide            # noqa
import _guide_rebuild, _guide_fit, _guide_audit                        # noqa
import randomizer                                                      # noqa
import zstandard, cryptography                                         # noqa
# 管线里用到、但 randgui.py 自己没用的标准库
import argparse, csv, ctypes, glob, hashlib, html, json, re, struct    # noqa
import xml.etree.ElementTree, urllib.request, urllib.error             # noqa
