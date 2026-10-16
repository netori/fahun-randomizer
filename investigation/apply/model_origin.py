# -*- coding: utf-8 -*-
"""用"贴图内部留着的原模型号"反推法魂新增模型是什么。

发现：法魂新增的模型（c5652 之类）在它们自己的贴图里**留着原模型的文件名**
（例如 c8007 的贴图叫 c3251_*，c2105 的叫 c2100_*）—— 于是原身可查，
再拿参考实现那份 23173 条人工名单去查原身的**名字与档位**，就有了答案。

产出：investigation/models_to_review.csv 补三列 —— 原身 / 建议名字 / 建议敌型 / 依据
"""
import collections
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, os.pardir))
sys.path.insert(0, HERE)
import chr_peek as CP                                               # noqa: E402
import erio                                                         # noqa: E402

CSVP = os.path.join(DATA, "models_to_review.csv")


def tex_model_names(model):
    """该模型 texbnd 里出现的所有 cXXXX 模型号（含它自己）"""
    out = set()
    for suf in ("_h", "_l", "_m", ""):
        p = os.path.join(CP.CHR, model + suf + ".texbnd.dcx")
        if not os.path.isfile(p):
            continue
        d = CP._plain(open(p, "rb").read())
        if d[:4] != b"BND4":
            continue
        for _n, x in erio.Bnd4.parse(d).files:
            x2 = CP._plain(x) if x[:4] == b"DCX\0" else x
            if x2[:4] != b"TPF\0":
                continue
            for s in re.findall(rb"(?:[\x20-\x7e]\x00){4,}", x2[:8192]):
                t = s.decode("utf-16le", "ignore").strip("\x00")
                for mm in re.findall(r"\b(c\d{3,4})_", t):
                    out.add(mm)
    return out


def model_file_names(model):
    """chrbnd/anibnd/behbnd 里露出的**别的模型号**（含材质路径 `C[c4240]_Hai` 这种写法）

    实测有效：c4251 的材质路径写着 `N:\\GR\\data\\Material\\mtd\\Chr\\C[c4240]_Hai...`、
    c5885 写着 `...\\Model\\chr\\c3350\\tex\\c3350_cha...` —— 原身一查就到。
    """
    out = set()
    for suf in (".chrbnd.dcx", ".anibnd.dcx", "_div00.anibnd.dcx", ".behbnd.dcx"):
        p = os.path.join(CP.CHR, model + suf)
        if not os.path.isfile(p):
            continue
        try:
            d = CP._plain(open(p, "rb").read())
        except Exception:
            continue
        blobs = [d]
        if d[:4] == b"BND4":
            try:
                blobs = []
                for _n, x in erio.Bnd4.parse(d).files:
                    blobs.append(CP._plain(x) if x[:4] == b"DCX\0" else x)
            except Exception:
                pass
        for b in blobs:
            head = b[:300000]
            for s1 in re.findall(rb"(?:[\x20-\x7e]\x00){5,}", head):      # UTF-16
                t = s1.decode("utf-16le", "ignore")
                out |= set(re.findall(r"c(\d{3,4})[_/\\]", t) and
                           ["c" + z for z in re.findall(r"\bc(\d{3,4})[_/\\]", t)])
                out |= {"c" + z for z in re.findall(r"C\[c(\d{3,4})\]", t)}
            for s2 in re.findall(rb"[\x20-\x7e]{6,}", head):               # ASCII
                t = s2.decode("ascii", "ignore")
                out |= {"c" + z for z in re.findall(r"\bc(\d{3,4})[_/\\]", t)}
                out |= {"c" + z for z in re.findall(r"C\[c(\d{3,4})\]", t)}
    return {x for x in out if x != model}


def main():
    ref = {}
    with open(os.path.join(DATA, "enemy_ref.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            ref[r["model"]] = r
    rows = list(csv.DictReader(open(CSVP, encoding="utf-8-sig")))
    cols = list(rows[0].keys())
    for c in ("原身（贴图里留的）", "建议名字", "建议敌型", "依据"):
        if c not in cols:
            cols.append(c)
    n_hit = 0
    for r in rows:
        m = r["model"]
        # 贴图里的名字 + 模型文件里的名字（材质路径/骨骼名常带原身）
        cand = sorted(tex_model_names(m) - {m} | model_file_names(m))
        if m == "c120" and "c0120" in ref:      # 三位号其实是四位（c120 = c0120）
            cand = ["c0120"] + cand
        r["原身（贴图里留的）"] = "、".join(cand)
        pick, why = "", ""
        # 优先挑"参考实现认得"的原身
        for c in cand:
            if c in ref:
                pick = c
                why = "贴图里留着 %s_* 的名字，原身 %s 在参考名单里" % (c, c)
                break
        if not pick and cand:
            pick = cand[0]
            why = "贴图里留着 %s_* 的名字（原身 %s 不在参考名单里，只能判到这一层）" % (c, cand[0])
        if pick:
            rr = ref.get(pick) or {}
            r["建议名字"] = (rr.get("extra_names") or "").split("、")[0]
            r["建议敌型"] = rr.get("ref_class_top") or ""
            r["依据"] = why
            n_hit += 1
        else:
            r.setdefault("建议名字", "")
            r.setdefault("建议敌型", "")
            r["依据"] = "贴图里没有留下别的模型号 —— 这条只能靠眼看/后续渲染网格"
    with open(CSVP, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print("39 个待确认模型里，靠贴图留名反推出原身+名字的: %d 个" % n_hit)
    print()
    print("%-8s %-10s %-30s %-14s %s" % ("模型", "原身", "建议名字", "建议敌型", "依据"))
    for r in rows:
        if r["原身（贴图里留的）"] or r["建议名字"]:
            print("%-8s %-10s %-30s %-14s %s" % (
                r["model"], (r["原身（贴图里留的）"] or "")[:10],
                (r["建议名字"] or "")[:30], (r["建议敌型"] or "")[:14], (r["依据"] or "")[:40]))
    print()
    print("没反推出来的:", [r["model"] for r in rows if not r["原身（贴图里留的）"]])
    print("→", CSVP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
