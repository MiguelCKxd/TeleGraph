# Publisher-only: build the Windows installer from a finished release ZIP.
#   powershell -NoProfile -ExecutionPolicy Bypass -File build_installer_vm.ps1 -Zip C:\...\TG-ASCII-1.3.2-windows-x64.zip [-Output C:\...]
param(
    [Parameter(Mandatory=$true)][string]$Zip,
    [string]$Output = '',
    [string]$Work = 'C:\tg-ascii-132\installer'
)
$ErrorActionPreference = 'Stop'
$iscc = Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'
if (-not (Test-Path $iscc)) { $iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' }
if (-not (Test-Path $iscc)) { throw 'Inno Setup 6 (ISCC.exe) not found' }
$name = [IO.Path]::GetFileNameWithoutExtension($Zip)          # TG-ASCII-1.3.2-windows-x64
if ($name -notmatch '^(?:TeleGraph|TG-ASCII)-(\d+\.\d+\.\d+(\.\d+)?)-windows-x64$') { throw "Unexpected ZIP name: $name" }
$version = $Matches[1]
if (-not $Output) { $Output = Split-Path -Parent $Zip }
$unpacked = Join-Path $Work 'app'
if (Test-Path $unpacked) { Remove-Item -Recurse -Force $unpacked }
New-Item -ItemType Directory -Force -Path $unpacked | Out-Null
Expand-Archive -LiteralPath $Zip -DestinationPath $unpacked -Force
$source = Join-Path $unpacked $name
if (-not (Test-Path (Join-Path $source 'TG-ASCII.exe'))) { throw 'TG-ASCII.exe missing in ZIP' }
$release = Get-Content (Join-Path $source 'release.json') -Raw | ConvertFrom-Json
if ($release.version -ne $version) { throw "release.json says $($release.version), ZIP says $version" }
# Local copy of the script and icon: ISCC resolves SourcePath next to the .iss.
$scriptDir = Join-Path $Work 'script'
New-Item -ItemType Directory -Force -Path $scriptDir | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'installer.iss') $scriptDir -Force
Copy-Item (Join-Path $PSScriptRoot 'app.ico') $scriptDir -Force
$log = Join-Path $Work 'iscc.log'
cmd /c "`"$iscc`" /Q /DMyAppVersion=$version `"/DSourceDir=$source`" `"/DOutputDir=$Output`" `"$scriptDir\installer.iss`" > `"$log`" 2>&1"
if ($LASTEXITCODE) { Get-Content $log -Tail 30; throw "ISCC failed ($LASTEXITCODE)" }
$setup = Join-Path $Output "TeleGraph-$version-Setup.exe"
Get-Item $setup | Select-Object FullName, Length
(Get-FileHash -Algorithm SHA256 $setup).Hash
