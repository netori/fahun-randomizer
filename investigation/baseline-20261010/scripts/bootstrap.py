"""Inventory only the specified MOD; validate and extract the supplied tool ZIP."""
from common import *
from pathlib import PurePosixPath
import zipfile, stat, collections, shutil

zip_path = WORKSPACE / 'WitchyBND-3.0.1.0-win-x64.zip'
book = WORKSPACE / '法魂资料整合表.xlsx'
print('cwd:', Path.cwd().resolve())
print('zip:', json.dumps(record_source(zip_path, 'downloaded tool ZIP'), ensure_ascii=False))
print('workbook:', json.dumps(record_source(book, 'reference workbook; first worksheet only'), ensure_ascii=False))
if not MOD.is_dir():
    raise SystemExit(f'Named MOD directory does not exist: {MOD}')
# Directory enumeration reads names/stat metadata only, not archive or game content.
files, directories = [], []
for root, dirs, names in os.walk(MOD, followlinks=False):
    root = Path(root)
    safe_dirs = []
    for name in sorted(dirs):
        p = root / name
        if p.is_symlink():
            directories.append({'relative_path': p.relative_to(MOD).as_posix(), 'symlink_skipped': True})
        else:
            directories.append({'relative_path': p.relative_to(MOD).as_posix()})
            safe_dirs.append(name)
    dirs[:] = safe_dirs
    for name in sorted(names):
        p = root / name
        files.append({'absolute_path': str(p.resolve()), 'relative_path': p.relative_to(MOD).as_posix(), 'size_bytes': p.stat().st_size, 'symlink': p.is_symlink()})
inventory = {'mod_root': str(MOD), 'directories': directories, 'files': files, 'file_count': len(files), 'total_size_bytes': sum(v['size_bytes'] for v in files)}
save_json(BASE / 'evidence/mod_structure.json', inventory)
print('mod file count:', len(files))
print('top-level names:', sorted({p['relative_path'].split('/')[0] for p in files}))
interesting = [p for p in files if Path(p['relative_path']).name.lower() == 'regulation.bin' or '/msg/' in ('/' + p['relative_path'].lower()) or p['relative_path'].lower().endswith(('.dll', '.toml', '.ini'))]
for entry in interesting:
    print(json.dumps(entry, ensure_ascii=False))
# Nearby packs: record names/stat only; do not open or mix their contents.
nearby = []
for p in sorted(MOD.parent.iterdir()):
    if p != MOD and p != WORKSPACE:
        nearby.append({'absolute_path': str(p.resolve()), 'name': p.name, 'type': 'directory' if p.is_dir() else 'file', 'size_bytes': p.stat().st_size if p.is_file() else None, 'content_not_read': True})
save_json(BASE / 'evidence/nearby_names_only.json', nearby)
entries = []
with zipfile.ZipFile(zip_path, 'r') as archive:
    seen = set()
    for item in archive.infolist():
        name = item.filename.replace('\\', '/')
        parts = PurePosixPath(name).parts
        mode = (item.external_attr >> 16) & 0xffff
        if not name or name.startswith('/') or name.startswith('\\') or any(v in ('.', '..') or ':' in v for v in parts) or stat.S_ISLNK(mode):
            raise ValueError(f'Unsafe ZIP member: {item.filename}')
        if name.casefold() in seen:
            raise ValueError(f'Duplicate case-insensitive ZIP member: {name}')
        seen.add(name.casefold())
        target = (TOOLS / name).resolve()
        if not inside(target, TOOLS):
            raise ValueError(f'ZIP traversal: {name}')
        entries.append({'name': item.filename, 'normalized_path': name, 'size_bytes': item.file_size, 'compressed_size_bytes': item.compress_size, 'crc32': f'{item.CRC:08x}', 'directory': item.is_dir(), 'external_attr': item.external_attr, 'target_absolute_path': str(target)})
    if len(entries) > 1000 or sum(v['size_bytes'] for v in entries) > 2 * 1024 ** 3:
        raise ValueError('Unexpected tool ZIP expansion; stopping')
    save_json(BASE / 'evidence/tool_zip_entries.json', {'entry_count': len(entries), 'path_traversal_check': 'passed', 'entries': entries})
    if TOOLS.exists() and any(TOOLS.iterdir()):
        raise FileExistsError(f'Tool directory contains unreviewed existing content: {TOOLS}')
    TOOLS.mkdir(parents=True, exist_ok=True)
    for item, entry in zip(archive.infolist(), entries):
        target = output_path(entry['target_absolute_path'])
        if item.is_dir():
            target.mkdir(exist_ok=True)
        else:
            with archive.open(item, 'r') as source, target.open('xb') as destination:
                shutil.copyfileobj(source, destination)
# Treat all distributed tool components as inputs, hash before executing/reading them.
for p in sorted(TOOLS.rglob('*')):
    if p.is_file():
        meta = record_source(p, 'extracted unmodified tool distribution input')
        print('tool input:', json.dumps(meta, ensure_ascii=False))
print('validated ZIP entries:', len(entries))
print('extraction complete:', TOOLS)
