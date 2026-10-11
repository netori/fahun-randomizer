# _guide_fit.py — 让每条说明书文本「不超过原长度」
#   背景：游戏按原版长度排版，文本变长会把尾部（近战职业的武器 / 法祷的卢恩）截掉
#   做法：① 先把冗长的地点措辞规则化缩写 ② 若仍超长，逐条缩短地点 ③ 不足的用零宽空格补齐
import os, re, sys
import xml.etree.ElementTree as ET

ZW = "\u200b"          # 零宽空格：游戏不显示，但占长度

# 地点措辞 → 更短的等价说法（按长度收益排序）
RULES = [
    # 观察到的长措辞（按“保留主体、去掉套话”处理）
    (re.compile(r"^击败(.+?)后可在解指处购买$"), r"\1"),
    (re.compile(r"^击败(.+?)后于解指处购买$"), r"\1"),
    (re.compile(r"^击败(.+?)后可购买$"), r"\1"),
    (re.compile(r"^击败(.+?)后可在.*?购买$"), r"\1"),
    (re.compile(r"^击败(.+?)后可获得$"), r"\1"),
    (re.compile(r"^发现(.+?)后由(.+?)给予$"), r"\1"),
    (re.compile(r"^发现(.+?)后(.+)$"), r"\1"),
    (re.compile(r"^(.+?)附近的神皮贵族后获得$"), r"\1"),
    (re.compile(r"^(.+?)上发现$"), r"\1"),
    (re.compile(r"^在(.+?)处的(.+)$"), r"\1"),
    (re.compile(r"^(.+?)解指处$"), r"\1"),
    (re.compile(r"^(.{10,}?)处$"), r"\1"),
    (re.compile(r"^由(.{1,20})出售$"), r"\1 处"),
    (re.compile(r"^由(.{1,20})掉落$"), r"\1"),
    (re.compile(r"^由(.{1,20})持有$"), r"\1"),
    (re.compile(r"^入侵击杀(.+)$"), r"\1"),
    (re.compile(r"^击杀(.+)$"), r"\1"),
    (re.compile(r"^击败(.+?)后获得$"), r"\1"),
    (re.compile(r"^击败(.+)$"), r"\1"),
    (re.compile(r"^在(.+?)协助(.+?)后给予$"), r"协助\2"),
    (re.compile(r"^在(.+?)后给予$"), r"\1"),
    (re.compile(r"^于(.+?)尸体上发现$"), r"\1"),
    (re.compile(r"^(.+?)附近的(.+)$"), r"\1"),
    (re.compile(r"^(.+?)边的(.+)$"), r"\1"),
    (re.compile(r"^(.+?)的(.+?)获得$"), r"\1"),
    (re.compile(r"^(.+?)获得$"), r"\1"),
    (re.compile(r"出售$"), ""),
    (re.compile(r"掉落$"), ""),
]


BAD = re.compile(r"[A-Za-z\[\]{}_]{2,}")


def is_bad_place(p: str) -> bool:
    """地点里出现内部英文名/符号 → 判定为无效地点"""
    return bool(BAD.search(p))


def shorten_place(p: str) -> str:
    """把一个地点串尽量缩短（不改语义主体）"""
    s = p.strip()
    for _ in range(4):
        for rx, rep in RULES:
            n = rx.sub(rep, s)
            if n and n != s and len(n) < len(s):
                s = n.strip()
                break
        else:
            break
    return s.strip(" -") or p


def rewrite(xml_new: str, xml_old: str, out: str, report=None):
    def rows(p):
        d = {}
        for e in ET.parse(p).getroot().iter():
            i = e.get("id")
            if i is not None and e.tag.lower().endswith("text"):
                d[int(i)] = e.text or ""
        return d
    new = rows(xml_new)
    old = rows(xml_old)
    stat = {"padded": 0, "shortened": 0, "still_long": 0}
    for i, t in list(new.items()):
        base = old.get(i)
        if base is None or not t:
            continue
        budget = len(base)
        if len(t) <= budget:
            if len(t) < budget:
                new[i] = t + ZW * (budget - len(t))     # 补齐到原长度
                stat["padded"] += 1
            continue
        # ① 先把无效（英文/符号）地点替换成原文里的对应地点，再看长度
        bad = re.findall(r" - ([^\n<]+)", t)
        if any(is_bad_place(x) for x in bad):
            pairs_old = dict(zip(re.findall(r"<font color=\"#FFA500\">([^<]+)</font>", base),
                                 [x.strip() for x in re.findall(r" - ([^\n<]+)", base)]))
            def _fix_one(m):
                item, dest = m.group(1), m.group(2)
                if is_bad_place(dest):
                    dest = pairs_old.get(item, "未知地点")
                return f'{item}</font> - {dest}'
            t = re.sub(r'<font color="#FFA500">([^<]+)</font> - ([^\n<]+)', _fix_one, t)
        # ② 超长 → 缩短各个地点
        parts = re.split(r"( - )", t)
        cand = []
        for seg in parts:
            if seg == " - ":
                cand.append(seg); continue
            cand.append(re.sub(r"([^\n<]+?)(?=\n|</font>|$)",
                               lambda m: shorten_place(m.group(1)), seg))
        t2 = "".join(cand)
        if len(t2) > budget:
            stat["still_long"] += 1
        else:
            stat["shortened"] += 1
        new[i] = t2 if len(t2) >= budget else t2 + ZW * (budget - len(t2))
    # 写回 XML（保持结构）
    tree = ET.parse(xml_new)
    for e in tree.getroot().iter():
        i = e.get("id")
        if i is not None and e.tag.lower().endswith("text") and int(i) in new:
            e.text = new[int(i)]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tree.write(out, encoding="utf-8", xml_declaration=True)
    if report is not None:
        report.update(stat)
    return stat


if __name__ == "__main__":
    import glob
    xs = sorted(glob.glob(os.path.join("work", "msg", "zh", "*.fmg.xml")), key=os.path.getmtime)
    depl = [x for x in xs if "deploy_" in x][-1]
    base = [x for x in xs if "deploy_" not in x][-1]
    out = os.path.join("work", "msg", "zh", "GoodsCaption.fitted.fmg.xml")
    st = rewrite(depl, base, out)
    print("  适配结果:", st, "→", out)
