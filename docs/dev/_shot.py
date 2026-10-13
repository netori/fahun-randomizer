# _shot.py — 给 GUI 截图（不杀 python，避免自杀）
import ctypes, os, subprocess, sys, time
from ctypes import wintypes

WS = os.path.dirname(os.path.abspath(__file__))
p = subprocess.Popen([sys.executable, os.path.join(WS, "randgui.py")], cwd=WS)
time.sleep(7)

u = ctypes.windll.user32
found = []


@ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
def cb(h, l):
    if u.IsWindowVisible(h):
        n = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(h, n, 256)
        if n.value and ("随机器" in n.value or "法魂" in n.value):
            found.append((h, n.value, ctypes.wintypes.RECT()))
    return True


u.EnumWindows(cb, 0)
print("  窗口:", [(h, t) for h, t, _ in found])
out = os.path.join(WS, "界面预览.png")
if found:
    h = found[0][0]
    u.ShowWindow(h, 9)
    u.SetForegroundWindow(h)
    u.BringWindowToTop(h)
    time.sleep(1.5)
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$b = New-Object Drawing.Bitmap 1100,780;"
        "$g = [Drawing.Graphics]::FromImage($b);"
        "$g.CopyFromScreen(0,0,0,0,$b.Size);"
        f"$b.Save('{out}');"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    print("  截图:", os.path.exists(out), os.path.getsize(out) if os.path.exists(out) else 0, r.stderr[:120])
else:
    print("  ✗ 没找到窗口")
p.terminate()
