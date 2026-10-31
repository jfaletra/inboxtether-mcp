"""Root-only reuse of the existing Argon2id enrollment; secret arrives by pipe."""
import json
import os
from pathlib import Path
import sys
if os.geteuid() != 0:
    raise SystemExit('Administrator enrollment required.')
sys.path.insert(0, '/opt/inboxtether')
from enroll_owner import make_record, write_record
value = json.loads(sys.stdin.buffer.read(8193))
try:
    write_record('/etc/inboxtether-approval/owner.json',
                 make_record(value['owner_id'], value['username'], value['password']), value['uid'])
    print('Dedicated owner hash stored privately.')
except Exception:
    raise SystemExit('Owner enrollment failed. No password or hash displayed.') from None
finally:
    value.clear()
