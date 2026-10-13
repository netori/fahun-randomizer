# N 网复核邮件（文件被隔离时用）

> 收件人：**support@nexusmods.com**
> ⚠️ 用**注册邮箱**发（N 网明确要求）✓，正文里带上**你的用户名** ✓
> ⚠️ 用**纯文本**发即可 ✓，不要加附件 ✓（对方要什么再给 ✓）

---

## 发送前只需填两处

| 要填的 | 从哪来 |
|---|---|
| `YOUR_NEXUS_USERNAME` | 你的 N 网用户名 |
| `MOD_PAGE_URL` | 你刚建的 mod 页地址（形如 `https://www.nexusmods.com/eldenring/mods/XXXXXXX`） |

---

## 英文正文（直接复制发送）

**Subject:**

```
Quarantine review request - Convergence Class Item Randomizer (PyInstaller tool, source included)
```

**Body:**

```
Hello,

I am the author of the mod "Convergence Class Item Randomizer" and one of my uploaded
files has been quarantined by your automated safety checks. I would like to request a
manual review.

My username: YOUR_NEXUS_USERNAME
Mod page: MOD_PAGE_URL

FILE IN QUESTION
  ConvergenceClassItemRandomizer_v1.1.0.zip
  SHA-256 (zip): 56bdbbd21c0ba0bc804c64d29482fa7d233aadc57bd1ed71d5a71d8a33fa9d02
  It contains a single Windows executable, ConvergenceClassItemRandomizer.exe,
  SHA-256: 6c1cc9c4e7e0b5e307a0151ca03ea03173688233a5c42563b577a555ade1ab0a

WHAT IT IS
  A single-player utility for ELDEN RING. It randomizes the items listed in the
  in-game class guides of a total-conversion mod (The Convergence / 法魂), by editing
  two data files that belong to that mod, which the user already has installed:
      mod\regulation.bin
      mod\msg\zhocn\item_dlc02.msgbnd.dcx
  It never modifies the game itself, and it is not usable online.

WHY IT IS AN EXECUTABLE
  It is a Python (tkinter) application packaged with PyInstaller - a standard and
  widely used packaging tool. I understand PyInstaller-packed executables are a common
  source of heuristic false positives in automated scanners; there is no obfuscation
  and no UPX compression.

WHAT IT DOES NOT DO
  - No network access of any kind: it does not download, upload, or phone home.
  - No installer, no service, no driver, no registry modification, no startup entry.
  - No administrator rights required. It runs as a normal user.
  - It does not patch, inject into, or modify game executables or game memory.
  - It writes only inside the mod folder it is placed in (adding its own helper
    files next to itself, and backing up the two data files before touching them).

SOURCE CODE AND BUILD STEPS
  The complete source is public here:
      https://github.com/netori/fahun-randomizer
  Build steps (Windows, Python 3.12):
      pip install pyinstaller zstandard cryptography
      git clone https://github.com/netori/fahun-randomizer
      cd fahun-randomizer
      python build_exe.py
  That produces the same executable. The repository also contains a README describing
  the tool, and the packaged resource set the build script assembles.

VERIFICATION
  If it helps, I am happy to upload the file to VirusTotal and send you the report
  link, or to provide any further information you need. Please let me know if you
  would like the file rebuilt in a different way.

Thank you for your time.

Best regards,
YOUR_NEXUS_USERNAME
```

---

## 中文对照（知道发出去的是什么）

**主题**：申请复核被隔离的文件（PyInstaller 工具，附源码）

**正文大意**：

```
你好，

我是 mod「Convergence Class Item Randomizer」的作者，我上传的一个文件被自动安全检查隔离了，
申请人工复核。

用户名：YOUR_NEXUS_USERNAME
mod 页：MOD_PAGE_URL

【被隔离的文件】
  ConvergenceClassItemRandomizer_v1.1.0.zip（附 SHA-256）
  里面是一个 exe（附 SHA-256）

【这是什么】
  一个 ELDEN RING 的单人工具。它把某个大改 MOD（The Convergence / 法魂）职业说明书里
  列出的道具做随机化，方式是改这个 MOD 自己的两个数据文件（玩家已经装了那个 MOD）：
      mod\regulation.bin
      mod\msg\zhocn\item_dlc02.msgbnd.dcx
  它不改游戏本体，也不能在联机时使用。

【为什么是 exe】
  这是一个 Python（tkinter）程序，用 PyInstaller 打包 —— 标准且常用的打包方式。
  我知道 PyInstaller 打的包在自动扫描里经常被误判；代码没有混淆，也没有用 UPX 压缩。

【它不做什么】
  · 完全无网络行为：不下载、不上传、不回传任何数据
  · 没有安装器、没有服务、没有驱动、不改注册表、不加开机启动项
  · 不需要管理员权限，普通用户即可运行
  · 不对游戏可执行文件做任何 patch / 注入，也不碰游戏内存
  · 只在自己所在的 MOD 目录里写东西（放自己的辅助文件；改动那两个数据文件前会先备份）

【源码与构建步骤】
  https://github.com/netori/fahun-randomizer
  Windows + Python 3.12：
      pip install pyinstaller zstandard cryptography
      git clone https://github.com/netori/fahun-randomizer
      cd fahun-randomizer
      python build_exe.py
  这样打出来的就是同一个可执行文件。

【可提供的验证】
  需要的话我可以把文件传 VirusTotal 把报告链接发你，或提供其它任何信息。

谢谢。
```

---

## 发送小抄（按顺序做）

1. 用**注册邮箱**发到 `support@nexusmods.com` ✓
2. 主题照抄 ✓；正文照抄 ✓，把两处占位换成真值 ✓
3. 哈希**已经填好了** ✓（就是这次发布包的真实值 ✓），不用再改 ✓
   - 若你之后重新打包过 ✓，用这条命令重新取一次 ✓：
     ```bat
     certutil -hashfile ConvergenceClassItemRandomizer_v1.1.0.zip SHA256
     certutil -hashfile ConvergenceClassItemRandomizer.exe SHA256
     ```
4. 等回信 ✓（一般几个工作日 ✓）。期间**别反复重传** ✗ —— 每次重传都会重新触发扫描 ✓

---

## 可选但很有效的一步

先自己传一次 **VirusTotal**（`virustotal.com` → 上传 zip 或 exe ✓），把报告链接贴进邮件 ✓。

- 报告里大概会有**少数几个**引擎报毒 ✓ —— 这很正常 ✓（PyInstaller 的典型特征 ✓），邮件里正好说明这一点 ✓
- 有**多数**引擎报毒才需要认真查 ✗（那说明确实有别的问题 ✓）

如果报告链接是公开的 ✓，写进邮件正文"VERIFICATION"那一段即可 ✓。
