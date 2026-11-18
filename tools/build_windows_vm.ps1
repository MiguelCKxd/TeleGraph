# Publisher-only: reproducible Windows x64 build/test inside the Parallels VM.
# Usage (inside Windows, as the normal user):
#   powershell -NoProfile -ExecutionPolicy Bypass -File build_windows_vm.ps1 -Source Z:\...\TG-ASCII-1.3.2 [-Credentials path.json] [-TestsOnly]
# Credentials JSON: {"id": <int>, "hash": "<str>"}; never committed, deleted by the caller.
param(
    [Parameter(Mandatory=$true)][string]$Source,
    [string]$Credentials = '',
    [string]$Work = 'C:\tg-ascii-132',
    [switch]$TestsOnly
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
if (-not (Test-Path $python)) { throw "Python 3.13 x64 not found at $python" }
$src = Join-Path $Work 'src'
New-Item -ItemType Directory -Force -Path $Work | Out-Null
# Local copy: building from the network share is slow and PyInstaller dislikes UNC paths.
robocopy $Source $src /MIR /XD .git .build-macos .build-windows-x64 releases __pycache__ /XF *.pyc .DS_Store /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with $LASTEXITCODE" }
$venv = Join-Path $Work 'venv'
if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) {
    & $python -m venv $venv
    if ($LASTEXITCODE) { throw 'venv creation failed' }
}
$vpy = Join-Path $venv 'Scripts\python.exe'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
Push-Location $src
try {
    & $vpy -m pip install -q --disable-pip-version-check -r requirements-build.txt
    if ($LASTEXITCODE) { throw 'requirements install failed' }
    cmd /c "`"$vpy`" tools\prepare_renderers.py > `"$Work\prepare.log`" 2>&1"
    $log = Join-Path $Work 'tests.log'
    # PowerShell 5 turns native stderr into terminating errors under 'Stop';
    # let cmd.exe redirect both streams instead.
    cmd /c "`"$vpy`" -m unittest discover -s tests > `"$log`" 2>&1"
    $testsExit = $LASTEXITCODE
    Get-Content $log -Tail 4
    if ($testsExit) { throw "unit tests failed ($testsExit), see $log" }
    if ($TestsOnly) { return }
    if (-not $Credentials -or -not (Test-Path $Credentials)) { throw 'Credentials file required for a user build.' }
    $creds = Get-Content $Credentials -Raw | ConvertFrom-Json
    $env:TG_APP_API_ID = [string]$creds.id
    $env:TG_APP_API_HASH = [string]$creds.hash
    $env:TG_BUILD_EMBED_APP_CREDENTIALS = 'yes'
    $out = Join-Path $Work 'releases'
    if (Test-Path $out) { Remove-Item -Recurse -Force $out }
    $buildLog = Join-Path $Work 'build.log'
    cmd /c "`"$vpy`" tools\build_release.py --output `"$out`" > `"$buildLog`" 2>&1"
    $buildExit = $LASTEXITCODE
    Remove-Item Env:TG_APP_API_ID, Env:TG_APP_API_HASH -ErrorAction SilentlyContinue
    Get-Content $buildLog -Tail 6
    if ($buildExit) { throw "build failed ($buildExit), see $buildLog" }
    Get-ChildItem $out
} finally { Pop-Location }
