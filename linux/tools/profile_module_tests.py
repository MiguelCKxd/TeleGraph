"""Record module/function invocation evidence, not line or branch coverage."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
import warnings

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
source=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(source))
package=str(source/'tg_ascii')+os.sep
calls={}
def profile(frame,event,arg):
    if event=='call':
        code=frame.f_code
        if code.co_filename.startswith(package):
            module=Path(code.co_filename).name
            # Class declarations execute code at import time but are not tested methods.
            if code.co_name=='<module>' or code.co_flags&2:
                calls.setdefault(module,set()).add((code.co_qualname,code.co_firstlineno))

warnings.simplefilter('error')
started=time.perf_counter()
sys.setprofile(profile);threading.setprofile(profile)
try:
    suite=unittest.defaultTestLoader.discover(str(source/'tests'))
    result=unittest.TextTestRunner(verbosity=1).run(suite)
finally:
    sys.setprofile(None);threading.setprofile(None)
report={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'skipped':len(result.skipped),'seconds':time.perf_counter()-started,
        'method':'sys.setprofile/threading.setprofile call events in this process; not line/branch coverage; subprocesses excluded',
        'modules':{path.name:{'imported':any(name=='<module>' for name,line in calls.get(path.name,())),
                              'functions':sorted([{'name':name,'line':line} for name,line in calls.get(path.name,())
                                                  if name!='<module>'],key=lambda row:row['line'])}
                   for path in sorted((source/'tg_ascii').glob('*.py'))}}
destination=args.output
destination.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({key:value for key,value in report.items() if key!='modules'},indent=2))
print(f'Evidence: {destination}')
raise SystemExit(not result.wasSuccessful())
