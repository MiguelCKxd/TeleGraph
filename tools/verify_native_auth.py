"""Read-only OS availability and canceled-request checks; never displays a prompt."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tg_ascii import native_auth


def run():
    available,label=native_auth.availability()
    cancelled=threading.Event();cancelled.set()
    result={'platform':sys.platform,'available':available,'label':label,'authentication_prompt_requested':False,
            'pre_cancelled_request_rejected':not native_auth.authenticate('Synthetic canceled verification',cancel_event=cancelled)}
    if sys.platform=='win32':
        try:native_auth._window_handle(0)
        except ValueError:result['invalid_window_rejected']=True
        else:result['invalid_window_rejected']=False
    result['success']=result['pre_cancelled_request_rejected'] and result.get('invalid_window_rejected',True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix='tg-auth-availability') as executor:result=executor.submit(run).result(20)
    text=json.dumps(result,indent=2,ensure_ascii=True)+'\n'
    if args.output:args.output.write_text(text,encoding='utf-8')
    print(text)
    return 0 if result['success'] else 1


if __name__=='__main__':raise SystemExit(main())
