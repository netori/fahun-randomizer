# -*- coding: utf-8 -*-
"""打发布包：把 exe + 玩家说明 + README + 更新日志 压成一个 zip。

用法：
    python make_release.py 1.3.0        # → ..\\发布包\\ConvergenceClassItemRandomizer_v1.3.0.zip
    python make_release.py 1.3.0 --out <输出目录>

为什么单独一支脚本：发布包的内容与命名要可复现 —— 以前是手工敲一长串 python -c，
敲错了才发现（包里少了说明 / 版本号写错）。这里把清单写死，并把每个文件的大小印出来。
"""
import argparse
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
WS = HERE
EXE = os.path.join(WS, 'dist_out', 'ConvergenceClassItemRandomizer.exe')
DEFAULT_OUT = os.path.normpath(os.path.join(WS, '..', '发布包'))

# (源路径, 包内路径) —— 顺序就是玩家解压后看到的顺序
FILES = [
    (EXE, 'ConvergenceClassItemRandomizer.exe'),
    (os.path.join(WS, 'docs', '使用说明（给玩家）.md'), '使用说明（给玩家）.md'),
    (os.path.join(WS, 'README.md'), 'README.md'),
]


def changelog(ver):
    p = os.path.join(WS, 'docs', '发布', f'更新日志_v{ver}.md')
    return (p, f'更新日志_v{ver}.md') if os.path.isfile(p) else None


def build(ver, out_dir):
    items = list(FILES)
    cl = changelog(ver)
    if cl:
        items.append(cl)
    missing = [src for src, _ in items if not os.path.isfile(src)]
    if missing:
        print('缺文件，没打包：')
        for m in missing:
            print('  ✗', m)
        return 1
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, f'ConvergenceClassItemRandomizer_v{ver}.zip')
    if os.path.isfile(dst):
        os.remove(dst)
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for src, arc in items:
            z.write(src, arc)
    print(f'✓ {dst}')
    print(f'  {os.path.getsize(dst) / 1048576:.2f} MB')
    with zipfile.ZipFile(dst) as z:
        for info in z.infolist():
            print(f'  · {info.filename}  {info.file_size / 1024:.0f} KB')
        bad = z.testzip()
    print('  zip 完整性：OK' if bad is None else f'  zip 损坏于 {bad}')
    return 0 if bad is None else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description='打发布包')
    ap.add_argument('version', help='版本号，如 1.3.0')
    ap.add_argument('--out', default=DEFAULT_OUT, help='输出目录（默认 ../发布包）')
    a = ap.parse_args(argv)
    return build(a.version, os.path.abspath(a.out))


if __name__ == '__main__':
    sys.exit(main())
