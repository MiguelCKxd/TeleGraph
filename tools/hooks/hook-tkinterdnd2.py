"""Bundle TkDnD for the interpreter architecture, including Tcl 8/9 variants."""
from pathlib import Path
import platform
import sysconfig
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

target = sysconfig.get_platform()
if platform.system() == 'Windows':
    prefix = {'win32': 'win-x86', 'win-amd64': 'win-x64', 'win-arm64': 'win-arm64'}[target]
elif platform.system() == 'Darwin':
    prefix = 'osx-arm64' if platform.machine().lower() == 'arm64' else 'osx-x64'
else:
    prefix = 'linux-arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'linux-x64'

datas = list({(source, destination)
              for source, destination in collect_data_files('tkinterdnd2') + collect_dynamic_libs('tkinterdnd2')
              if Path(destination).name in (prefix, prefix + '-tcl9')})
