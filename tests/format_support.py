"""Self-contained synthetic legacy-format fixture; never opens a real mailbox."""
import os,tempfile,unittest
from pathlib import Path
from organizer.model import Config,CATEGORIES,OrganizerError
from organizer.service import Organizer
from organizer.store import Store
from synthetic_mailbox import SyntheticMailbox
from test_organizer import mail,policy

class Harness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state'
        self.path.mkdir(mode=0o700)
        self.now = 1000.0
        self.policy = policy()
        self.box = SyntheticMailbox([mail()], clock=lambda: self.now)
        self.config = Config('owner@example.com', 'mail.example.com', 'owner',
                             {k: self.box.validities[k] for k in CATEGORIES}, moves_enabled=True)
        self.store = Store(self.path, {'host': self.config.host, 'account': self.config.account, 'owner': self.config.owner})
        self.org = Organizer(self.config, self.policy, self.store, self.box, clock=lambda: self.now)

    def frozen(self):
        run = self.org.start_run()['run_id']
        while self.org.classify_page(run)['remaining']:
            pass
        return self.org.prepare_batch(run)

    def approved(self):
        batch = self.frozen()
        self.org.decide(batch['batch_id'], batch['fingerprint'], True,
                        {'method': 'trusted-terminal', 'uid': os.geteuid()})
        return batch

    def execute_all(self, batch):
        for move in self.store.record('batches', batch['batch_id'])['manifest']['moves']:
            self.org.execute(batch['batch_id'], move['uid'])
        return self.org.batch_status(batch['batch_id'])
