"""Publisher setup: use prebuilt native accelerators when available."""
import subprocess
import sys

RENDERERS = ['rlottie-python>=1.3.8,<2', 'av>=16,<20', 'resvg-py>=0.5,<1']
CALL_ENGINE = 'ntgcalls==3.0.5'
GROUP_ENGINE = 'py-tgcalls==3.0.0'

def main():
    print('Preparando cifrado nativo para transferencias: cryptg', flush=True)
    result = subprocess.run([sys.executable, '-m', 'pip', 'install',
                             '--only-binary=:all:', '--retries', '0',
                             '--timeout', '15', 'cryptg==0.6.0'])
    if result.returncode:
        print('Cifrado nativo no disponible para este Python/arquitectura. '
              'Telethon usara su alternativa compatible.', flush=True)
    for requirement in RENDERERS:
        print('Preparando motor visual:',requirement,flush=True)
        result=subprocess.run([sys.executable,'-m','pip','install','--only-binary=:all:','--retries','0','--timeout','15',requirement])
        if result.returncode:
            print('Motor no disponible para este Python/arquitectura. La app conservara la vista estatica o indicara el formato no disponible.',flush=True)
    from native_engine_wheel import bundled_engine
    engine = bundled_engine() or CALL_ENGINE
    print('Preparando motor opcional de llamadas:', engine, flush=True)
    result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--only-binary=:all:',
                             '--retries', '0', '--timeout', '15', engine, GROUP_ENGINE])
    if result.returncode and sys.platform.startswith('linux'):
        # 1.5.5: no 3.0.5 wheels for Linux; the official 3.0.7 keeps the same API
        # (per-participant volume is shown only when the engine supports it).
        print('Linux: probando el motor oficial ntgcalls 3.0.7', flush=True)
        result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--only-binary=:all:',
                                 '--retries', '0', '--timeout', '15', 'ntgcalls==3.0.7', GROUP_ENGINE])
    if result.returncode:
        print('No hay motor de llamadas compatible con este Python/arquitectura. '
              'No se mostraran botones de llamada; el resto de la app sigue disponible. '
              'Usa Python 3.12/3.13 y una arquitectura con rueda publicada para incluir llamadas.', flush=True)
    elif sys.platform == 'darwin':
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--only-binary=:all:',
                        '--retries', '0', '--timeout', '15', 'pyobjc-framework-AVFoundation>=10'])
    return 0

if __name__=='__main__':raise SystemExit(main())
