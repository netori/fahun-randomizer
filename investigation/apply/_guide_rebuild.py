# _guide_rebuild.py — 按正确方向重写说明书的地点
#   规则（用户定义）：**物品名不动，只换它现在所在的地点**
#   X 现在所在格子原本放的是 Y ⇒ X 的新地点 = Y 的地点（Y 的地点见基准说明书）
#   例：葛瑞克骑士头盔 搬进原本放「百智腿甲」的格子 → 写成「葛瑞克骑士头盔 - 学院结晶洞窟」
import collections, csv, os, re
import xml.etree.ElementTree as ET

APPLY = os.path.dirname(os.path.abspath(__file__))
# 注意：地点后面可能紧跟收尾标签（如 </font>）——必须原样保留，否则字号/颜色会变
LINE = re.compile(r'^(.*?)(<font color="#FFA500">)([^<]+)(</font>)( - )([^\n<]*)(.*)$')
GIDS = list(range(8800, 8827)) + list(range(8870, 8896))


def load_rows(p):
    d = {}
    for e in ET.parse(p).getroot().iter():
        i = e.get("id")
        if i is not None and e.tag.lower().endswith("text"):
            d[int(i)] = e.text or ""
    return d


def item_place_from(xml_path):
    """物品名 -> 地点（同一物品多处出现时取第一个）"""
    m = {}
    for _i, t in load_rows(xml_path).items():
        for item, dest in re.findall(r'<font color="#FFA500">([^<]+)</font> - ([^\n<]*)', t):
            m.setdefault(item.strip(), dest.strip())
    return m


def plan_pairs(plan_csv, name_of):
    """返回 (新物品名 -> 原占用者物品名, 新物品名集合)"""
    new2old = {}
    with open(plan_csv, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["old"] == r["new"]:
                continue
            onm = name_of(tuple(r["old"].split(":")))
            nnm = name_of(tuple(r["new"].split(":")))
            if onm and nnm:
                new2old.setdefault(nnm, onm)
    return new2old


def rewrite(deploy_xml, baseline_xml, plan_csv, out, name_of, report=None):
    base_place = item_place_from(baseline_xml)
    new2old = plan_pairs(plan_csv, name_of)
    rows = load_rows(deploy_xml)
    stat = collections.Counter()
    new_rows = {}
    for eid in GIDS:
        t = rows.get(eid)
        if not t:
            continue
        out_lines = []
        for ln in t.split("\n"):
            m = LINE.match(ln)
            if not m:
                out_lines.append(ln)
                continue
            pre, tag_o, item, tag_c, dash, dest, tail = m.groups()
            item = item.strip()
            occ = new2old.get(item)                     # 该物品搬到了谁的格子里
            newdest = base_place.get(occ) if occ else None
            if not newdest:
                stat["未动/保持"] += 1
                out_lines.append(ln)
                continue
            if newdest == dest.strip():
                stat["地点未变"] += 1
            else:
                stat["换地点"] += 1
            out_lines.append(f"{pre}{tag_o}{item}{tag_c}{dash}{newdest}{tail}")
        new_rows[eid] = "\n".join(out_lines)

    tree = ET.parse(deploy_xml)
    for e in tree.getroot().iter():
        i = e.get("id")
        if i is not None and e.tag.lower().endswith("text") and int(i) in new_rows:
            e.text = new_rows[int(i)]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tree.write(out, encoding="utf-8", xml_declaration=True)
    stat["可换但未换"] = sum(1 for _ in ())
    if report is not None:
        report.update(stat)
    return stat


if __name__ == "__main__":
    import glob, sys
    sys.path.insert(0, APPLY)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "r", os.path.join(APPLY, "..", "randomization-dryrun", "scripts", "randomizer.py"))
    r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
    items = r.load_world(False, "guide")

    def name_of(k):
        v = items.get(k)
        return (v or {}).get("name", "")

    base = os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.fmg.xml")
    xs = sorted(glob.glob(os.path.join(APPLY, "work", "msg", "zh", "*.fmg.xml")), key=os.path.getmtime)
    depl = [x for x in xs if "deploy_" in x and "fitted" not in x][-1]
    plan = [x for x in glob.glob(os.path.join(APPLY, "out", "boot_全部混合_80.csv"))] or ["out/boot_全部混合_80.csv"]
    out = os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.rebuilt.fmg.xml")
    st = rewrite(depl, base, plan[0], out, name_of)
    print("  重写统计:", dict(st))
    print("  →", out)
