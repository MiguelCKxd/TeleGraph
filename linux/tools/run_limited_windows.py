"""Run one isolated demo check inside a Windows Job Object.

Example (Windows, graphical desktop, 64-bit Python):
  python tools/run_limited_windows.py --memory-mib 384 --cpu-percent 20 --output limited.json
  python tools/run_limited_windows.py --memory-mib 256 --cpu-percent 10 --output smaller.json

Only this fresh demo process and its children are limited. No VM, OS, account or
other application settings change. Memory is committed private memory, not an
RSS limit or emulated total system RAM. CPU is a job-wide hard rate, not a model
of a particular low-end CPU. No functionality is disabled to meet the budget.
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEMO_SCRIPTS = ('verify_contact_card.py', 'verify_customization_images.py', 'verify_layout.py')


def demo_command(script, output):
    if script not in DEMO_SCRIPTS:
        raise ValueError('Only packaged, isolated demo checks can be run.')
    source = Path(__file__).resolve().parent / script
    if not source.is_file():
        raise ValueError('The selected demo check is not installed.')
    return [sys.executable, str(source), '--output', str(output)]


def checked_limits(memory_mib, cpu_percent, timeout):
    if type(memory_mib) is not int or not 96 <= memory_mib <= 16384:
        raise ValueError('Memory must be between 96 and 16384 MiB.')
    if type(cpu_percent) is not int or not 1 <= cpu_percent <= 100:
        raise ValueError('CPU rate must be between 1 and 100 percent.')
    if type(timeout) is not int or not 10 <= timeout <= 600:
        raise ValueError('Watchdog must be between 10 and 600 seconds.')
    return memory_mib * 1024 * 1024, cpu_percent * 100


def accounting_metrics(accounting):
    """Job CPU includes the application spawned by a venv redirector/launcher."""
    return {'job_cpu_seconds': (accounting.TotalKernelTime + accounting.TotalUserTime) / 10_000_000,
            'job_kernel_seconds': accounting.TotalKernelTime / 10_000_000,
            'job_user_seconds': accounting.TotalUserTime / 10_000_000,
            'job_total_processes': accounting.TotalProcesses,
            'job_active_processes_at_report': accounting.ActiveProcesses,
            'job_terminated_processes': accounting.TotalTerminatedProcesses}


def run_windows(command, output, memory_mib, cpu_percent, timeout):
    if sys.platform != 'win32':
        raise RuntimeError('Windows Job Objects require Windows.')
    import msvcrt
    from ctypes import wintypes as w

    size_t = ctypes.c_size_t
    ull = ctypes.c_ulonglong
    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ull) for name in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                                           'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]
    class BASIC_LIMIT(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                    ('LimitFlags', w.DWORD), ('MinimumWorkingSetSize', size_t), ('MaximumWorkingSetSize', size_t),
                    ('ActiveProcessLimit', w.DWORD), ('Affinity', size_t), ('PriorityClass', w.DWORD),
                    ('SchedulingClass', w.DWORD)]
    class EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', BASIC_LIMIT), ('IoInfo', IO_COUNTERS),
                    ('ProcessMemoryLimit', size_t), ('JobMemoryLimit', size_t),
                    ('PeakProcessMemoryUsed', size_t), ('PeakJobMemoryUsed', size_t)]
    class CPU_LIMIT(ctypes.Structure):
        _fields_ = [('ControlFlags', w.DWORD), ('CpuRate', w.DWORD)]
    class BASIC_ACCOUNTING(ctypes.Structure):
        _fields_ = [('TotalUserTime', ctypes.c_longlong), ('TotalKernelTime', ctypes.c_longlong),
                    ('ThisPeriodTotalUserTime', ctypes.c_longlong), ('ThisPeriodTotalKernelTime', ctypes.c_longlong),
                    ('TotalPageFaultCount', w.DWORD), ('TotalProcesses', w.DWORD),
                    ('ActiveProcesses', w.DWORD), ('TotalTerminatedProcesses', w.DWORD)]
    class STARTUPINFO(ctypes.Structure):
        _fields_ = [('cb', w.DWORD), ('lpReserved', w.LPWSTR), ('lpDesktop', w.LPWSTR),
                    ('lpTitle', w.LPWSTR), ('dwX', w.DWORD), ('dwY', w.DWORD),
                    ('dwXSize', w.DWORD), ('dwYSize', w.DWORD), ('dwXCountChars', w.DWORD),
                    ('dwYCountChars', w.DWORD), ('dwFillAttribute', w.DWORD), ('dwFlags', w.DWORD),
                    ('wShowWindow', w.WORD), ('cbReserved2', w.WORD), ('lpReserved2', ctypes.POINTER(w.BYTE)),
                    ('hStdInput', w.HANDLE), ('hStdOutput', w.HANDLE), ('hStdError', w.HANDLE)]
    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [('hProcess', w.HANDLE), ('hThread', w.HANDLE), ('dwProcessId', w.DWORD), ('dwThreadId', w.DWORD)]
    class MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [('cb', w.DWORD), ('PageFaultCount', w.DWORD), ('PeakWorkingSetSize', size_t),
                    ('WorkingSetSize', size_t), ('QuotaPeakPagedPoolUsage', size_t), ('QuotaPagedPoolUsage', size_t),
                    ('QuotaPeakNonPagedPoolUsage', size_t), ('QuotaNonPagedPoolUsage', size_t),
                    ('PagefileUsage', size_t), ('PeakPagefileUsage', size_t), ('PrivateUsage', size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    signatures = {
        'CreateJobObjectW': ([w.LPVOID, w.LPCWSTR], w.HANDLE),
        'SetInformationJobObject': ([w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD], w.BOOL),
        'QueryInformationJobObject': ([w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, w.LPVOID], w.BOOL),
        'AssignProcessToJobObject': ([w.HANDLE, w.HANDLE], w.BOOL),
        'CreateProcessW': ([w.LPCWSTR, w.LPWSTR, w.LPVOID, w.LPVOID, w.BOOL, w.DWORD, w.LPVOID,
                            w.LPCWSTR, ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESS_INFORMATION)], w.BOOL),
        'ResumeThread': ([w.HANDLE], w.DWORD),
        'WaitForSingleObject': ([w.HANDLE, w.DWORD], w.DWORD),
        'GetExitCodeProcess': ([w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
        'GetProcessTimes': ([w.HANDLE, ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME),
                             ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME)], w.BOOL),
        'TerminateJobObject': ([w.HANDLE, w.UINT], w.BOOL),
        'TerminateProcess': ([w.HANDLE, w.UINT], w.BOOL),
        'CloseHandle': ([w.HANDLE], w.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(MEMORY_COUNTERS), w.DWORD]
    psapi.GetProcessMemoryInfo.restype = w.BOOL
    memory_bytes, cpu_rate = checked_limits(memory_mib, cpu_percent, timeout)
    outcome = {'success': False, 'platform': sys.platform, 'memory_limit_mib': memory_mib,
               'cpu_rate_percent': cpu_percent, 'watchdog_seconds': timeout,
               'scope': 'fresh demo process and descendants only',
               'memory_metric': 'committed private memory; not system RAM or RSS',
               'script': Path(command[1]).name, 'attached_before_start': False,
               'watchdog_triggered': False, 'launcher_samples': 0, 'launcher_peak_working_set_bytes': 0,
               'launcher_peak_private_commit_bytes': 0,
               'process_sample_scope': 'initial launcher only; the application may run in a child process',
               'job_accounting_available': False}
    process, job, stage, data = PROCESS_INFORMATION(), None, 'job_create', None
    started = time.monotonic()
    try:
        job = kernel.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = EXTENDED_LIMIT()
        limits.BasicLimitInformation.LimitFlags = 0x100 | 0x200 | 0x2000  # process + job memory; kill on close
        limits.ProcessMemoryLimit = limits.JobMemoryLimit = memory_bytes
        stage = 'memory_limit'
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        cpu = CPU_LIMIT(0x1 | 0x4, cpu_rate)  # ENABLE | HARD_CAP
        stage = 'cpu_limit'
        if not kernel.SetInformationJobObject(job, 15, ctypes.byref(cpu), ctypes.sizeof(cpu)):
            raise ctypes.WinError(ctypes.get_last_error())
        log = output.with_suffix('.child.log')
        data = tempfile.TemporaryDirectory(prefix='tg-ascii-limited-demo-')
        with log.open('wb') as log_file, open(os.devnull, 'rb') as null_file:
            stdout = msvcrt.get_osfhandle(log_file.fileno())
            stdin = msvcrt.get_osfhandle(null_file.fileno())
            os.set_handle_inheritable(stdout, True)
            os.set_handle_inheritable(stdin, True)
            info = STARTUPINFO()
            info.cb = ctypes.sizeof(info)
            info.dwFlags = 0x100  # STARTF_USESTDHANDLES
            info.hStdInput, info.hStdOutput, info.hStdError = stdin, stdout, stdout
            environment = {**os.environ, 'TG_ASCII_DATA_DIR': data.name, 'PYTHONUNBUFFERED': '1'}
            block = ctypes.create_unicode_buffer('\0'.join(f'{k}={v}' for k, v in sorted(environment.items(), key=lambda item: item[0].upper())) + '\0\0')
            args = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
            stage = 'create_suspended'
            try:
                created = kernel.CreateProcessW(command[0], args, None, None, True,
                                                0x4 | 0x400, block, str(Path(__file__).resolve().parents[1]),
                                                ctypes.byref(info), ctypes.byref(process))
            finally:
                os.set_handle_inheritable(stdout, False)
                os.set_handle_inheritable(stdin, False)
            if not created:
                raise ctypes.WinError(ctypes.get_last_error())
            stage = 'attach_job'
            if not kernel.AssignProcessToJobObject(job, process.hProcess):
                raise ctypes.WinError(ctypes.get_last_error())
            outcome['attached_before_start'] = True
            stage = 'resume'
            if kernel.ResumeThread(process.hThread) == 0xffffffff:
                raise ctypes.WinError(ctypes.get_last_error())
            stage = 'running'
            while True:
                counters = MEMORY_COUNTERS()
                counters.cb = ctypes.sizeof(counters)
                if psapi.GetProcessMemoryInfo(process.hProcess, ctypes.byref(counters), counters.cb):
                    outcome['launcher_samples'] += 1
                    outcome['launcher_peak_working_set_bytes'] = max(outcome['launcher_peak_working_set_bytes'], counters.PeakWorkingSetSize)
                    outcome['launcher_peak_private_commit_bytes'] = max(outcome['launcher_peak_private_commit_bytes'], counters.PeakPagefileUsage, counters.PrivateUsage)
                state = kernel.WaitForSingleObject(process.hProcess, 200)
                if state == 0:
                    break
                if state != 258:
                    raise ctypes.WinError(ctypes.get_last_error())
                if time.monotonic() - started > timeout:
                    outcome['watchdog_triggered'] = True
                    kernel.TerminateJobObject(job, 124)
                    kernel.WaitForSingleObject(process.hProcess, 5000)
                    break
            code = w.DWORD()
            if kernel.GetExitCodeProcess(process.hProcess, ctypes.byref(code)):
                outcome['exit_code'] = code.value
            created_time, ended_time, kernel_time, user_time = (w.FILETIME() for _ in range(4))
            if kernel.GetProcessTimes(process.hProcess, ctypes.byref(created_time), ctypes.byref(ended_time),
                                      ctypes.byref(kernel_time), ctypes.byref(user_time)):
                outcome['launcher_cpu_seconds'] = sum((stamp.dwHighDateTime << 32) | stamp.dwLowDateTime
                                                      for stamp in (kernel_time, user_time)) / 10_000_000
            if kernel.QueryInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits), None):
                outcome['peak_job_commit_bytes'] = limits.PeakJobMemoryUsed
                outcome['peak_single_process_commit_bytes'] = limits.PeakProcessMemoryUsed
            accounting = BASIC_ACCOUNTING()
            if kernel.QueryInformationJobObject(job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None):
                outcome['job_accounting_available'] = True
                outcome.update(accounting_metrics(accounting))
            outcome['success'] = outcome.get('exit_code') == 0 and not outcome['watchdog_triggered']
    except Exception as error:  # noqa: BLE001 -- the diagnostic report must survive any native runner failure
        outcome.update(error=type(error).__name__, stage=stage)
        if isinstance(getattr(error, 'winerror', None), int):
            outcome['winerror'] = error.winerror
    finally:
        # Includes a failed assignment: a suspended process must never survive
        # or start outside its limits. Closing the job terminates all children.
        if process.hProcess:
            if kernel.WaitForSingleObject(process.hProcess, 0) == 258:
                kernel.TerminateProcess(process.hProcess, 125)
                kernel.WaitForSingleObject(process.hProcess, 5000)
            kernel.CloseHandle(process.hThread)
            kernel.CloseHandle(process.hProcess)
        if job:
            kernel.CloseHandle(job)
        if data is not None:
            try:
                data.cleanup()
            except OSError:
                outcome.update(success=False, cleanup_error=True)
        outcome['wall_seconds'] = round(time.monotonic() - started, 3)
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--script', choices=DEMO_SCRIPTS, default='verify_contact_card.py')
    parser.add_argument('--memory-mib', type=int, default=384)
    parser.add_argument('--cpu-percent', type=int, default=20)
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    checked_limits(args.memory_mib, args.cpu_percent, args.timeout)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    child_output = output.with_suffix('.child.json')
    command = demo_command(args.script, child_output)
    if sys.platform != 'win32':
        outcome = {'success': False, 'platform': sys.platform, 'error': 'WindowsRequired'}
    else:
        # A previous report must not be mistaken for this run's result.
        child_output.unlink(missing_ok=True)
        outcome = run_windows(command, output, args.memory_mib, args.cpu_percent, args.timeout)
        try:
            child = json.loads(child_output.read_text(encoding='utf-8'))
            outcome['demo_success'] = child.get('success') is True
        except (OSError, ValueError, AttributeError):
            outcome['demo_success'] = False
        outcome['success'] = outcome['success'] and outcome['demo_success']
    output.write_text(json.dumps(outcome, indent=2), encoding='utf-8')
    print(json.dumps(outcome))
    return 0 if outcome['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
