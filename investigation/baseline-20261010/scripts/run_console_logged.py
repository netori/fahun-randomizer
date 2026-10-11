"""Use built-in Windows ConPTY for tools requiring a console; no packages/settings changed.
No interactive input is sent. stdout/stderr share the OS terminal stream and are documented as merged.
"""
import ctypes as C
from ctypes import wintypes as W
import json, os, re, subprocess, sys, threading, time
from common import BASE, output_path, save_json, now

if len(sys.argv) < 4 or sys.argv[2] != '--':
    raise SystemExit('Usage: run_console_logged.py <unique label> -- <exe> [args...]')
label, argv = sys.argv[1], sys.argv[3:]
if not label.replace('_', '').replace('-', '').isalnum():
    raise SystemExit('Unsafe label')
paths = {k: output_path(BASE / 'logs' / f'{label}.{k}') for k in ['stdout.txt', 'stderr.txt', 'console.raw', 'command.json']}
if any(p.exists() for p in paths.values()):
    raise SystemExit('Refusing existing console log')
k = C.WinDLL('kernel32', use_last_error=True)
class COORD(C.Structure):
    _fields_ = [('X', W.SHORT), ('Y', W.SHORT)]
class STARTUPINFOW(C.Structure):
    _fields_ = [('cb', W.DWORD), ('lpReserved', W.LPWSTR), ('lpDesktop', W.LPWSTR), ('lpTitle', W.LPWSTR), ('dwX', W.DWORD), ('dwY', W.DWORD), ('dwXSize', W.DWORD), ('dwYSize', W.DWORD), ('dwXCountChars', W.DWORD), ('dwYCountChars', W.DWORD), ('dwFillAttribute', W.DWORD), ('dwFlags', W.DWORD), ('wShowWindow', W.WORD), ('cbReserved2', W.WORD), ('lpReserved2', C.POINTER(W.BYTE)), ('hStdInput', W.HANDLE), ('hStdOutput', W.HANDLE), ('hStdError', W.HANDLE)]
class STARTUPINFOEXW(C.Structure):
    _fields_ = [('StartupInfo', STARTUPINFOW), ('lpAttributeList', C.c_void_p)]
class PROCESS_INFORMATION(C.Structure):
    _fields_ = [('hProcess', W.HANDLE), ('hThread', W.HANDLE), ('dwProcessId', W.DWORD), ('dwThreadId', W.DWORD)]
k.CreatePipe.argtypes = [C.POINTER(W.HANDLE), C.POINTER(W.HANDLE), C.c_void_p, W.DWORD]
k.CreatePipe.restype = W.BOOL
k.CreatePseudoConsole.argtypes = [COORD, W.HANDLE, W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
k.CreatePseudoConsole.restype = C.c_long
k.ClosePseudoConsole.argtypes = [W.HANDLE]
k.ClosePseudoConsole.restype = None
k.InitializeProcThreadAttributeList.argtypes = [C.c_void_p, W.DWORD, W.DWORD, C.POINTER(C.c_size_t)]
k.InitializeProcThreadAttributeList.restype = W.BOOL
k.UpdateProcThreadAttribute.argtypes = [C.c_void_p, W.DWORD, C.c_size_t, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p]
k.UpdateProcThreadAttribute.restype = W.BOOL
k.DeleteProcThreadAttributeList.argtypes = [C.c_void_p]
k.CreateProcessW.argtypes = [W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p, W.BOOL, W.DWORD, C.c_void_p, W.LPCWSTR, C.POINTER(STARTUPINFOEXW), C.POINTER(PROCESS_INFORMATION)]
k.CreateProcessW.restype = W.BOOL
k.ReadFile.argtypes = [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
k.ReadFile.restype = W.BOOL
k.CloseHandle.argtypes = [W.HANDLE]
k.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
k.WaitForSingleObject.restype = W.DWORD
k.GetExitCodeProcess.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
k.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
def check(value):
    if not value:
        raise C.WinError(C.get_last_error())
    return value
start = now()
meta = {'label': label, 'argv': argv, 'windows_command_line': subprocess.list2cmdline(argv), 'cwd': os.getcwd(), 'started_utc': start, 'runner_argv': sys.argv, 'execution_environment': 'Windows built-in ConPTY; no interactive input; no environment/settings mutation', 'stream_separation': 'ConPTY merges stdout/stderr; stdout.txt is de-ANSI merged terminal output, console.raw retains exact terminal bytes', 'timeout_seconds': 120}
handles = []
hpc = W.HANDLE()
attr = None
proc = PROCESS_INFORMATION()
chunks = []
reader = None
code = 125
try:
    ir, iw, ore, ow = W.HANDLE(), W.HANDLE(), W.HANDLE(), W.HANDLE()
    check(k.CreatePipe(C.byref(ir), C.byref(iw), None, 0))
    check(k.CreatePipe(C.byref(ore), C.byref(ow), None, 0))
    handles.extend([ir, iw, ore, ow])
    result = k.CreatePseudoConsole(COORD(160, 50), ir, ow, 0, C.byref(hpc))
    if result != 0:
        raise RuntimeError(f'CreatePseudoConsole HRESULT {result:#x}')
    size = C.c_size_t()
    k.InitializeProcThreadAttributeList(None, 1, 0, C.byref(size))
    attr = C.create_string_buffer(size.value)
    check(k.InitializeProcThreadAttributeList(attr, 1, 0, C.byref(size)))
    check(k.UpdateProcThreadAttribute(attr, 0, 0x00020016, hpc, C.sizeof(W.HANDLE), None, None))
    si = STARTUPINFOEXW()
    si.StartupInfo.cb = C.sizeof(si)
    si.lpAttributeList = C.cast(attr, C.c_void_p)
    cmd = C.create_unicode_buffer(subprocess.list2cmdline(argv))
    def read_stream():
        buf, readn = C.create_string_buffer(65536), W.DWORD()
        while k.ReadFile(ore, buf, len(buf), C.byref(readn), None):
            if not readn.value:
                break
            chunks.append(buf.raw[:readn.value])
    reader = threading.Thread(target=read_stream, daemon=True)
    reader.start()
    check(k.CreateProcessW(argv[0], cmd, None, None, False, 0x00080000, None, os.getcwd(), C.byref(si), C.byref(proc)))
    meta['pid'] = proc.dwProcessId
    wait = k.WaitForSingleObject(proc.hProcess, 120000)
    if wait == 0x102:
        check(k.TerminateProcess(proc.hProcess, 124))
        k.WaitForSingleObject(proc.hProcess, 5000)
        meta['terminated_on_timeout'] = True
    exit_code = W.DWORD()
    check(k.GetExitCodeProcess(proc.hProcess, C.byref(exit_code)))
    code = exit_code.value
except Exception as exc:
    meta['runner_error'] = repr(exc)
    chunks.append(('\nRUNNER_ERROR: ' + repr(exc) + '\n').encode('utf-8'))
finally:
    if hpc:
        k.ClosePseudoConsole(hpc)
    if reader:
        reader.join(timeout=5)
    if attr:
        k.DeleteProcThreadAttributeList(attr)
    for handle in handles + [proc.hThread, proc.hProcess]:
        if handle:
            k.CloseHandle(handle)
raw = b''.join(chunks)
with paths['console.raw'].open('xb') as stream:
    stream.write(raw)
text = raw.decode('utf-8', errors='replace')
text = re.sub(r'\x1b\][^\x07]*(?:\x07|\x1b\\)', '', text)
text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
text = re.sub(r'\x1b[()][A-Z0-9]', '', text)
text = text.replace('\r\n', '\n').replace('\r', '\n')
with paths['stdout.txt'].open('x', encoding='utf-8', newline='\n') as stream:
    stream.write(text)
with paths['stderr.txt'].open('x', encoding='utf-8') as stream:
    stream.write('STREAM_SEPARATION_UNAVAILABLE: ConPTY merges stdout/stderr. Consult console.raw and stdout.txt.\n')
meta.update({'finished_utc': now(), 'exit_code': code, 'stdout_path': str(paths['stdout.txt']), 'stderr_path': str(paths['stderr.txt']), 'raw_console_path': str(paths['console.raw'])})
save_json(paths['command.json'], meta)
print(json.dumps(meta, ensure_ascii=False))
sys.exit(code if code <= 255 else 125)
