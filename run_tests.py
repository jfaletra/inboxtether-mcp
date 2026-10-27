"""Run only local synthetic tests; reject IP sockets in this test process."""
import io,json,logging,os,sys,unittest,stat,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
os.environ['PYTHONDONTWRITEBYTECODE']='1'
# Clear operational settings so an operator's environment cannot select real resources.
for key in list(os.environ):
    if key.startswith('INBOXTETHER_'):os.environ.pop(key)
def guard(event,args):
    if event in ('socket.connect','socket.bind') and isinstance(args[1],tuple):
        raise AssertionError('Synthetic tests forbid IP network access')
sys.addaudithook(guard)
logging.disable(logging.CRITICAL)
def cases(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from cases(item)
        else:yield item
def private_test_directory():
    # Owner-enrollment fixtures deliberately reject world-writable ancestors.
    # A short private home path also avoids the Unix socket pathname length limit.
    for base in (Path.home().resolve(), ROOT):
        ancestry=(base, *base.parents)
        if all(stat.S_ISDIR(p.lstat().st_mode) and p.lstat().st_uid in (0,os.geteuid())
               and not (stat.S_IMODE(p.lstat().st_mode) & 0o022) for p in ancestry):
            try:
                return tempfile.TemporaryDirectory(prefix='.ibt-tests-',dir=base)
            except PermissionError:
                continue
    raise RuntimeError('Tests need a writable private checkout or home directory')

with private_test_directory() as private_temp:
    tempfile.tempdir=private_temp
    os.environ['TMPDIR']=private_temp
    unique={test.id():test for test in cases(unittest.defaultTestLoader.discover(str(ROOT/'tests')))}
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(unique.values()))
    print(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
                      'skipped':len(result.skipped),'synthetic_only':True}))
    sys.exit(not result.wasSuccessful())
