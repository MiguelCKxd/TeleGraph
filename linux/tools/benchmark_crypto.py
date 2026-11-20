"""Account-free AES-IGE CPU measurement using the installed Telethon engines."""
import argparse
import json
from pathlib import Path
import platform
import time
from unittest.mock import patch

from telethon.crypto import aes


def measure():
    # Fixed synthetic bytes: no credentials, session material or real messages.
    payload=bytes(range(256))*512
    key=bytes(range(32));iv=bytes(reversed(range(32)))
    engine='cryptg' if aes.cryptg else 'libssl' if aes.libssl.encrypt_ige else 'pyaes'
    rows=[]
    def run(label):
        started=time.perf_counter();cpu=time.process_time()
        encrypted=aes.AES.encrypt_ige(payload,key,iv)
        assert aes.AES.decrypt_ige(encrypted,key,iv)==payload
        elapsed=time.perf_counter()-started
        rows.append({'engine':label,'roundtrip_bytes':len(payload)*2,'seconds':elapsed,
                     'cpu_seconds':time.process_time()-cpu,'roundtrip_mib_per_second':len(payload)*2/elapsed/1024**2})
    run(engine)
    if engine!='pyaes':
        with patch.object(aes,'cryptg',None),patch.object(aes.libssl,'encrypt_ige',None),patch.object(aes.libssl,'decrypt_ige',None):run('pyaes')
    return {'success':True,'python':platform.python_version(),'system':platform.system(),
            'architecture':platform.machine(),'selected_engine':engine,'measurements':rows,
            'scope':'Synthetic AES-IGE only; not network throughput or Telegram performance'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path)
    args=parser.parse_args();report=json.dumps(measure(),indent=2)+'\n'
    if args.output:args.output.write_text(report,encoding='utf-8')
    print(report)


if __name__=='__main__':main()
