# _rel_v110.py — 建 v1.1.0 Release 并上传附件（GitHub API 抖动时自动重试）
import hashlib
import os
import subprocess
import time

REPO, TAG = "netori/fahun-randomizer", "v1.1.0"
ZIP = "ConvergenceClassItemRandomizer_v1.1.0.zip"
NOTES = "docs/RELEASE_v1.1.0.md"
TITLE = "v1.1.0 · 法魂职业道具和装备随机器（中文版）"


def sh(*a):
    r = subprocess.run(a, capture_output=True)
    out = (r.stdout or b"") + (r.stderr or b"")
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return out.decode("gbk", "replace")


def main():
    sh256 = hashlib.sha256(open(ZIP, "rb").read()).hexdigest()
    print(f"[{time.strftime('%H:%M:%S')}] 目标 {TAG} ｜ {ZIP} "
          f"{os.path.getsize(ZIP)/1048576:.2f} MB ｜ sha256 {sh256[:16]}", flush=True)

    ready = False
    for attempt in range(1, 181):                      # 最多约 3 小时
        out = sh("gh", "release", "view", TAG, "--repo", REPO, "--json", "tagName")
        if "502" in out or "Bad Gateway" in out:
            print(f"[{time.strftime('%H:%M:%S')}] 第{attempt}次 API 不可用，60 秒后再试", flush=True)
            time.sleep(60)
            continue
        if TAG in out:
            ready = True
        else:
            r = sh("gh", "release", "create", TAG, "--repo", REPO, "--title", TITLE,
                   "--notes-file", NOTES)
            if "502" in r or "Bad Gateway" in r or "error" in r.lower():
                print(f"[{time.strftime('%H:%M:%S')}] 建 release 失败: {r.strip()[:70]}，60 秒后再试", flush=True)
                time.sleep(60)
                continue
            ready = True
            print(f"[{time.strftime('%H:%M:%S')}] ✓ Release {TAG} 已建立", flush=True)
        break

    if not ready:
        print(f"[{time.strftime('%H:%M:%S')}] ✗ 重试用尽，Release 未建立", flush=True)
        return 1

    for attempt in range(1, 181):
        info = sh("gh", "release", "view", TAG, "--repo", REPO, "--json", "assets",
                  "--jq", '.assets[] | .name + " " + (.size|tostring)')
        if "502" in info or "Bad Gateway" in info:
            print(f"[{time.strftime('%H:%M:%S')}] 第{attempt}次查附件失败，60 秒后再试", flush=True)
            time.sleep(60)
            continue
        if ZIP in info and str(os.path.getsize(ZIP)) in info:
            print(f"[{time.strftime('%H:%M:%S')}] ✓✓ 附件已在，无需重传\n{info}", flush=True)
            break
        r = sh("gh", "release", "upload", TAG, ZIP, "--repo", REPO, "--clobber")
        if "502" in r or "Bad Gateway" in r or "error" in r.lower():
            print(f"[{time.strftime('%H:%M:%S')}] 第{attempt}次上传失败: {r.strip()[:70]}，60 秒后再试", flush=True)
            time.sleep(60)
            continue
        chk = sh("gh", "release", "view", TAG, "--repo", REPO, "--json", "assets",
                 "--jq", '.assets[] | .name + " " + (.size|tostring) + " 下载" + (.downloadCount|tostring) + "次"')
        print(f"[{time.strftime('%H:%M:%S')}] ✓✓ 上传成功：\n{chk}", flush=True)
        break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
