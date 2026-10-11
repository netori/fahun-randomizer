"""Capture exact subprocess argv, stdout, stderr and exit code without shell mutation."""
import json, os, subprocess, sys, time
from common import BASE, now, output_path, save_json

if len(sys.argv) < 4 or sys.argv[2] != '--':
    raise SystemExit('Usage: run_logged.py <unique label> -- <executable> [args...]')
label = sys.argv[1]
if not label.replace('_', '').replace('-', '').isalnum():
    raise SystemExit('Unsafe log label')
argv = sys.argv[3:]
logs = BASE / 'logs'
paths = {kind: output_path(logs / f'{label}.{kind}') for kind in ['stdout.txt', 'stderr.txt', 'command.json']}
if any(p.exists() for p in paths.values()):
    raise SystemExit(f'Refusing to overwrite existing logs: {label}')
start = now()
record = {'label': label, 'argv': argv, 'windows_command_line': subprocess.list2cmdline(argv), 'cwd': os.getcwd(), 'started_utc': start, 'runner_argv': sys.argv}
with paths['stdout.txt'].open('xb') as out, paths['stderr.txt'].open('xb') as err:
    try:
        result = subprocess.run(argv, cwd=os.getcwd(), stdin=subprocess.DEVNULL, stdout=out, stderr=err, shell=False)
        code = result.returncode
    except Exception as exc:
        err.write((repr(exc) + '\n').encode('utf-8'))
        code = 125
record.update({'finished_utc': now(), 'exit_code': code, 'stdout_path': str(paths['stdout.txt']), 'stderr_path': str(paths['stderr.txt']), 'stdin': 'DEVNULL', 'shell': False})
save_json(paths['command.json'], record)
print(json.dumps(record, ensure_ascii=False))
# The outer bash result must retain the actual command result.
sys.exit(code)
