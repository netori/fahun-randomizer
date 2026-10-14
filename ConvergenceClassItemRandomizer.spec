# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['randgui.py', '_bundle_stub.py'],   # 桩文件只为让打包器看到运行时加载的管线依赖
    pathex=['investigation/apply', 'investigation/randomization-dryrun/scripts'],
    binaries=[],
    datas=[('_assets', '_assets')],   # 运行时最小集：写入管线 + 引擎 + 目录数据 + 说明书基准
    hiddenimports=['zstandard', 'cryptography', 'planlib'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ConvergenceClassItemRandomizer',
    icon='_assets/deco/app.ico',      # exe / 任务栏图标（AI 生的金符文徽记）
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
