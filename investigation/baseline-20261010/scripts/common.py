"""Read-only source registry and constrained investigation output helpers."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os

WORKSPACE = Path(r'F:/game/studygame/elden ring/THE_COVERAGE-随机开发/随机mod').resolve()
BASE = WORKSPACE / 'investigation/baseline-20261010'
TOOLS = WORKSPACE / 'tools/witchybnd-3.0.1.0'
MOD = Path(r'F:/game/studygame/elden ring/THE_COVERAGE-随机开发/法魂mod V3.0.2 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.2）').resolve()
REGISTRY = BASE / 'source_registry.json'

def now():
    return datetime.now(timezone.utc).isoformat()

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def inside(path, root):
    return Path(path).resolve().is_relative_to(Path(root).resolve())

def output_path(path):
    p = Path(path).resolve()
    if not (inside(p, BASE) or inside(p, TOOLS)):
        raise ValueError(f'Write forbidden outside dedicated directories: {p}')
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def save_json(path, value, exclusive=True):
    p = output_path(path)
    with p.open('x' if exclusive else 'w', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')

def record_source(path, role):
    p = Path(path).resolve(strict=True)
    if not p.is_file():
        raise ValueError(f'Not a regular input: {p}')
    key = str(p)
    data = json.loads(REGISTRY.read_text(encoding='utf-8')) if REGISTRY.exists() else {'created_utc': now(), 'sources': {}}
    if key not in data['sources']:
        data['sources'][key] = {'absolute_path': key, 'size_bytes': p.stat().st_size, 'sha256_initial': sha256(p), 'roles': [role], 'recorded_before_read_utc': now()}
    else:
        if p.stat().st_size != data['sources'][key]['size_bytes'] or sha256(p) != data['sources'][key]['sha256_initial']:
            raise ValueError(f'Previously registered input changed: {p}')
        if role not in data['sources'][key]['roles']:
            data['sources'][key]['roles'].append(role)
    save_json(REGISTRY, data, exclusive=False)
    return data['sources'][key]

def record_tree_inputs(root, role):
    result = []
    for p in sorted(Path(root).rglob('*')):
        if p.is_file():
            result.append(record_source(p, role))
    return result

def copy_registered(source, destination, role):
    import shutil
    meta = record_source(source, role)
    target = output_path(destination)
    if target.exists():
        raise FileExistsError(f'Refusing unknown existing destination: {target}')
    shutil.copy2(source, target)
    if sha256(target) != meta['sha256_initial']:
        raise ValueError(f'Copy hash mismatch: {target}')
    return {'source': str(Path(source).resolve()), 'copy': str(target), 'size_bytes': meta['size_bytes'], 'sha256': meta['sha256_initial']}

if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == 'register':
        for name in sys.argv[2:]:
            print(json.dumps(record_source(name, 'explicit read input'), ensure_ascii=False))
    else:
        raise SystemExit('Use: common.py register <explicit path>...')
