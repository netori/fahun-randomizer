# 后台重试上传发布包：GitHub REST API 抖动时（502）自动等待重试
import hashlib, json, os, subprocess, sys, time

REPO, TAG = "netori/fahun-randomizer", "v1.1.0"
ZIP = "ConvergenceClassItemRandomizer_v1.1.0.zip"
SH = hashlib.sha256(open(ZIP, "rb").read()).hexdigest()
print(f"[{time.strftime('%H:%M:%S')}] 目标: {ZIP}  {os.path.getsize(ZIP)/1048576:.2f} MB  sha256 {SH[:16]}", flush=True)


def sh(*a):
    r = subprocess.run(a, capture_output=True, text=True)
    return (r.stdout or "") + (r.stderr or "")


for attempt in range(1, 121):                       # 最多约 2 小时
    out = sh("gh", "release", "view", TAG, "--repo", REPO, "--json", "assets",
             "--jq", ".assets[] | .name + \" \" + (.size|tostring)")
    if "502" in out or "Bad Gateway" in out or not out.strip():
        print(f"[{time.strftime('%H:%M:%S')}] 第{attempt}次 API 不可用，60 秒后再试", flush=True)
        time.sleep(60); continue
    if ZIP in out and str(os.path.getsize(ZIP)) in out:
        print(f"[{time.strftime('%H:%M:%S')}] ✓ 附件已是新包，无需重传", flush=True); break
    r = sh("gh", "release", "upload", TAG, ZIP, "--repo", REPO, "--clobber")
    if "502" in r or "Bad Gateway" in r or "error" in r.lower():
        print(f"[{time.strftime('%H:%M:%S')}] 第{attempt}次上传失败: {r.strip()[:70]}，60 秒后再试", flush=True)
        time.sleep(60); continue
    chk = sh("gh", "release", "view", TAG, "--repo", REPO, "--json", "assets",
             "--jq", ".assets[] | .name + \" \" + (.size|tostring) + \" 下载\" + (.downloadCount|tostring) + \"次\"")
    print(f"[{time.strftime('%H:%M:%S')}] ✓✓ 上传成功。当前附件:\n{chk}", flush=True)
    break
else:
    print(f"[{time.strftime('%H:%M:%S')}] ✗ 重试用尽，仍未成功", flush=True)
