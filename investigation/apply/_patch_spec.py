# _patch_spec.py — 按《随机化算法规格》对齐三处
#   ① 档位跨度改为均匀 4 档：span = 1 + round((1-coh)*3)
#   ② 武器/护甲/卢恩 档位统一夹到 0..3
#   ③ 法师/祷告域整体不参与档位（护甲已在隔离；武器同样不分级）
import ast, os

APPLY = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(os.path.dirname(APPLY))
P = os.path.join(WS, "investigation", "randomization-dryrun", "scripts", "randomizer.py")
src = open(P, encoding="utf-8").read()
before = src
done = []

# ① 跨度公式：4 档均匀
old1 = "    steps = int(round((1.0 - _coh) * 4.0))"
new1 = '''    # 规格 §2.4：统一 4 档，跨度均匀
    #   跨度 = 1 + round((1-合理度)*3)  → 100%:1 ／ 67%:2 ／ 33%:3 ／ 0%:4
    steps = max(0, min(3, int(round((1.0 - _coh) * 3.0))))'''
if old1 in src:
    src = src.replace(old1, new1, 1); done.append("① 跨度改 4 档均匀")

# ②/③ 档位统一 0..3 + 法祷整域不分级 → 统一入口
helper = '''

def _spec_tier(u, items):
    """《算法规格》§2 的统一档位：0..3（夹取）；法师/祷告域整域不参与档位（返回 None）"""
    try:
        v = items.get(u.get("base") or (u.get("items") or [None])[0]) or {}
        arch = u.get("arch") or v.get("arch") or ""
        if arch in CASTER_ARCH:
            return None                      # 法祷整域不分级（隔离在池键里做）
        t = u.get("_tier")
        if not isinstance(t, (int, float)):
            t = _tier_of_unit(u)
        return max(0, min(3, int(t)))
    except Exception:
        return 2

'''
if "_spec_tier" not in src:
    anchor = "def _unit_tier_any(u, items):"
    if anchor in src:
        src = src.replace(anchor, helper.strip("\n") + "\n\n" + anchor, 1)
        done.append("②③ 新增 _spec_tier（0..3 夹取 + 法祷不分级）")

if src != before:
    ast.parse(src)
    open(P, "w", encoding="utf-8").write(src)
    print(f"  ✓ 已写入（{len(before)} → {len(src)} 字符）｜ 改动: {done}")
else:
    print("  无改动")
now = open(P, encoding="utf-8").read()
print(f"  核对: 4档跨度 {'有' if '统一 4 档，跨度均匀' in now else '无'} ｜ _spec_tier {'有' if 'def _spec_tier' in now else '无'}")
