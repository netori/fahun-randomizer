# N 网文件解封邮件 · v1.4.2

> 用途：N 网自动安检把上传的文件隔离（"This file has been quarantined by our automated safety checks"）。
> 收件人：support@nexusmods.com
> 发件建议：用你 N 网账号绑定的邮箱发；把 [MOD_PAGE_URL]、[NEXUS_USERNAME]、[YOUR_NAME] 换成真实值。
> 附件不必带 exe；如果 support 要，再按回信提供。GitHub 源码是公开的，能直接验证构建。

## 主题

```text
Quarantined file review request — Convergence Item & Enemy Randomizer v1.4.2 (Elden Ring)
```

## 正文

```text
Hello Nexus Mods Support,

I am the author of "Convergence Item & Enemy Randomizer (法魂 物品与敌人随机器)" for ELDEN RING. My first upload was automatically quarantined by your safety checks, and I would like to request a manual review so the file can be published.

Mod page: [MOD_PAGE_URL]
Account: [NEXUS_USERNAME]
File: ConvergenceClassItemRandomizer V1.4.2
Uploaded: 25 Oct 2026, 2:57 PM
Version: 1.4.2
Size: 19.6 MB
SHA-256 (ZIP): C4DD7B1251A1FD5A2A4F268BE2086825AAF44EDB26420F8B2C703D6F3B3D14CB
SHA-256 (EXE): 828848B87B2C17BB6C1D83B224219CF2A4D05A89C3519153FBF2EA831244C156

The quarantine notice lists three possible reasons: executables, internal file scanners / VirusTotal, and nested archives. I believe this is a false positive:

1. The file is a Windows GUI application written in Python 3.12 and packaged with PyInstaller (one-file, windowed, unsigned, no UPX). PyInstaller's one-file bootloader is a self-extracting executable, which commonly triggers heuristic detections.
2. The ZIP is flat: it contains the exe plus an offline HTML tutorial and three Markdown documents. There are no nested archives inside it.
3. The application is an offline single-player randomizer. It reads the user's local ELDEN RING / The Convergence installation, then writes its own plan and overlay-layer files. It makes no network connections. It does not modify the base mod (the overlay is mounted through YAFSML's Plan= line and can be switched back with one click). It redistributes no game or mod files.

Source code (public): https://github.com/netori/fahun-randomizer
Branch: main. The v1.4.2 build corresponds to commit e9e48a7; later commits only add documentation.

Build steps (reproducible on Windows 10/11 x64):
1. Install Python 3.12 x64.
2. git clone https://github.com/netori/fahun-randomizer.git
3. python -m pip install pyinstaller zstandard cryptography
4. python build_exe.py
5. Output: dist_out\ConvergenceClassItemRandomizer.exe

build_exe.py runs PyInstaller with ConvergenceClassItemRandomizer.spec (--noconfirm --distpath dist_out --workpath build_out), then runs four isolated self-checks (--selftest / --planlib / --uicheck / --uitest) in an empty temporary folder.

I am happy to provide any of the following if useful:
- the exact source archive for the release commit,
- a VirusTotal report or additional scan results,
- build logs,
- any other information your review process requires.

Could you please review the file and lift the quarantine so it can be published? If there is a preferred way to submit source/build proof, please let me know and I will follow it.

Thank you for your time,
[YOUR_NAME]
[YOUR_EMAIL]
```

## 可随信附上的事实（回信再给）

- 发行包内 5 个文件（无嵌套压缩包）：ConvergenceClassItemRandomizer.exe 20,793,425 B；使用教学.html 83,783 B；使用说明（给玩家）.md 42,326 B；README.md 36,600 B；更新日志_v1.4.2.md 10,318 B。
- ZIP 20,560,835 B；EXE 是 PyInstaller one-file、windowed、未签名、upx=False。
- 源码分支 main，仓库公开可匿名访问；build_exe.py 与 spec 文件都在仓库根目录。
