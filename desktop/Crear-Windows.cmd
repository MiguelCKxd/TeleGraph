@echo off
setlocal EnableExtensions DisableDelayedExpansion
title TG-ASCII - Crear descarga para Windows
pushd "%~dp0"
if errorlevel 1 goto path_error
if not exist "tools\build_release.py" goto source_missing
if not exist "requirements-build.txt" goto source_missing

echo TG-ASCII Desktop - Crear una app Windows
echo Elige la arquitectura de la descarga:
echo   1. x64: PCs Intel/AMD de 64 bits
echo   2. ARM64: Windows ARM, incluido Parallels en Apple Silicon
echo   3. x86: Windows de 32 bits
choice /C 123 /N /M "Arquitectura [1/2/3]: "
if errorlevel 3 goto target_x86
if errorlevel 2 goto target_arm64
if errorlevel 1 goto target_x64
goto cancelled
:target_x86
set "TG_TARGET=x86"
set "TG_PLATFORM=win32"
set "TG_PY_TAG=3.13-32"
set "TG_PY_FOLDER=Python313-32"
set "TG_INSTALL_NAME=python-3.13.15.exe"
set "TG_INSTALL_SHA=741c07276eb2d57e7ee012d643f021c58cb38d11c5389be46c15d41d1a10b447"
goto selected_target
:target_arm64
set "TG_TARGET=arm64"
set "TG_PLATFORM=win-arm64"
set "TG_PY_TAG=3.13-arm64"
set "TG_PY_FOLDER=Python313-arm64"
set "TG_INSTALL_NAME=python-3.13.15-arm64.exe"
set "TG_INSTALL_SHA=c252c676087c49e6b94e95a273536b78921c28a5fc9f86d15d25392328247249"
goto selected_target
:target_x64
set "TG_TARGET=x64"
set "TG_PLATFORM=win-amd64"
set "TG_PY_TAG=3.13"
set "TG_PY_FOLDER=Python313"
set "TG_INSTALL_NAME=python-3.13.15-amd64.exe"
set "TG_INSTALL_SHA=edec09c4853aeae9ac36efb8c9f95b6b8e2fee65eee56d9767a8b7c69c574403"
:selected_target
echo Esta herramienta es para Miguel, el creador de la app.
echo Tus amigos recibiran el ZIP final y abriran TG-ASCII.exe sin consola.
echo.
call :find_python
if defined TG_BUILD_PYTHON goto environment

echo Falta Python 3.13 %TG_TARGET%. Se puede instalar para tu usuario de Windows.
choice /C SN /N /M "Descargar e instalar Python oficial para esta arquitectura? [S/N]: "
if errorlevel 2 goto cancelled
if errorlevel 1 goto install_python
goto cancelled

:install_python
set "TG_INSTALL_FILE=%TEMP%\tg-ascii-%TG_INSTALL_NAME%"
echo Descargando el instalador oficial de python.org y verificando SHA-256...
powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; try { Invoke-WebRequest -UseBasicParsing -Uri ('https://www.python.org/ftp/python/3.13.15/' + $env:TG_INSTALL_NAME) -OutFile $env:TG_INSTALL_FILE; if ((Get-FileHash -Algorithm SHA256 -LiteralPath $env:TG_INSTALL_FILE).Hash -ne $env:TG_INSTALL_SHA) { throw 'SHA-256 no coincide; no se ejecutara el instalador.' }; exit 0 } catch { Write-Host $_; exit 1 }"
if errorlevel 1 goto install_error
start "" /wait "%TG_INSTALL_FILE%" /passive InstallAllUsers=0 Include_tcltk=1 Include_launcher=0 Include_test=0 PrependPath=0 TargetDir="%LOCALAPPDATA%\Programs\Python\%TG_PY_FOLDER%"
if errorlevel 3011 goto install_error
if errorlevel 3010 goto restart_needed
if errorlevel 1 goto install_error
call :find_python
if not defined TG_BUILD_PYTHON goto manual_python

:environment
echo.
echo [1/4] Preparando el entorno de compilacion...
"%TG_BUILD_PYTHON%" -m venv ".build-windows-%TG_TARGET%"
if errorlevel 1 goto failed
set "TG_BUILD_VENV=%CD%\.build-windows-%TG_TARGET%\Scripts\python.exe"
"%TG_BUILD_VENV%" -c "import sys,sysconfig; sys.exit(0 if sysconfig.get_platform() == '%TG_PLATFORM%' else 1)"
if errorlevel 1 goto wrong_architecture
echo.
echo [2/4] Instalando las herramientas de compilacion...
if "%TG_TARGET%"=="x86" (
  "%TG_BUILD_VENV%" -m pip install numpy==2.2.6
  if errorlevel 1 goto failed
)
"%TG_BUILD_VENV%" -m pip install -r requirements-build.txt
if errorlevel 1 goto failed
"%TG_BUILD_VENV%" -c "import tkinter; print('Tk disponible')"
if errorlevel 1 goto failed
echo.
"%TG_BUILD_VENV%" tools\prepare_renderers.py
echo [3/4] Comprobando el proyecto...
"%TG_BUILD_VENV%" -m unittest discover -s tests -v
if errorlevel 1 goto failed
echo.
echo [4/4] Elige la descarga que quieres crear:
echo   1. Version para amigos: usa las claves API de tu app TG-ASCII.
echo   2. Demo local: no necesita claves y no conecta con Telegram.
choice /C 12 /N /M "Escribe 1 o 2: "
if errorlevel 2 goto demo_build
if errorlevel 1 goto full_build
goto cancelled

:full_build
echo.
echo Introduce el API ID y hash de tu app en esta ventana, no en el chat.
echo No se pide tu codigo de acceso, tu contrasena ni tu sesion personal.
"%TG_BUILD_VENV%" tools\build_release.py --launch
if errorlevel 1 goto failed
goto success

:demo_build
"%TG_BUILD_VENV%" tools\build_release.py --launch --demo-only
if errorlevel 1 goto failed
goto success

:success
echo.
echo ZIP creado en la carpeta releases.
echo App creada. Se ha solicitado abrirla automaticamente.
popd
pause
exit /b 0

:find_python
set "TG_BUILD_PYTHON="
if not exist "%LOCALAPPDATA%\Programs\Python\%TG_PY_FOLDER%\python.exe" goto launcher_python
set "TG_BUILD_PYTHON=%LOCALAPPDATA%\Programs\Python\%TG_PY_FOLDER%\python.exe"
call :check_python
if defined TG_BUILD_PYTHON exit /b 0
:launcher_python
for /f "delims=" %%P in ('py -V:PythonCore/%TG_PY_TAG% -c "import sys; print(sys.executable)" 2^>nul') do set "TG_BUILD_PYTHON=%%P"
if not defined TG_BUILD_PYTHON exit /b 0
call :check_python
exit /b 0

:check_python
"%TG_BUILD_PYTHON%" -c "import sys,sysconfig; sys.exit(0 if sys.version_info[:2] == (3,13) and sysconfig.get_platform() == '%TG_PLATFORM%' else 1)" >nul 2>&1
if errorlevel 1 set "TG_BUILD_PYTHON="
exit /b 0

:manual_python
echo.
echo No se ha encontrado Python 3.13 %TG_TARGET%.
echo Instala Python 3.13 para Windows desde https://www.python.org/downloads/windows/
echo Elige el instalador para %TG_TARGET% y vuelve a abrir Crear-Windows.cmd.
goto failed

:restart_needed
echo Python solicita reiniciar Windows. Reinicia y vuelve a abrir este archivo.
goto failed

:install_error
echo.
echo Windows no ha podido instalar Python. Revisa el mensaje anterior.
echo Si pide reiniciar Windows, reinicia y vuelve a abrir este archivo.
goto failed

:wrong_architecture
echo.
echo El entorno no es %TG_TARGET%. Renombra la carpeta .build-windows-%TG_TARGET% y reintenta.
goto failed

:source_missing
echo Extrae TODO el ZIP antes de abrir Crear-Windows.cmd.
goto failed

:cancelled
echo Preparacion cancelada.
popd
pause
exit /b 1

:failed
echo.
echo No se ha terminado. Copia el error anterior o haz una captura para revisarlo.
popd
pause
exit /b 1

:path_error
echo No se pudo abrir la carpeta del proyecto. Extrae el ZIP en Descargas de Windows.
pause
exit /b 1
