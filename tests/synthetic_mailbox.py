"""In-memory synthetic mailbox; no network, credentials, filesystem mail or scheduling."""
from dataclasses import replace

from organizer.model import CATEGORIES, digest, require


class SimulatedCrash(BaseException):
    """Models process death, bypassing normal exception recovery."""


class SyntheticMailbox:
    def __init__(self, messages=(), clock=lambda: 0):
        self.validities = {'INBOX': 100, **{name: i + 200 for i, name in enumerate(CATEGORIES)}}
        self.boxes = {name: {} for name in self.validities}
        self.next_uids = {name: 1 for name in self.validities}
        self.clock = clock
        self.moves = []
        self.reads = []
        self.fault = None
        for message in messages:
            self.add(message)

    def add(self, message, folder='INBOX'):
        require(message.uid not in self.boxes[folder], 'Synthetic UID reused.')
        self.boxes[folder][message.uid] = message
        self.next_uids[folder] = max(self.next_uids[folder], message.uid + 1)

    def inbox_identity(self):
        return self.validities['INBOX'], self.next_uids['INBOX']

    def folder(self, category):
        require(category in self.boxes, 'Synthetic destination missing.')
        return self.validities[category]

    def uids(self, low, high):
        return sorted(uid for uid in self.boxes['INBOX'] if low <= uid <= high)

    def fetch(self, folder, uv, uid):
        require(self.validities[folder] == uv, 'Synthetic UIDVALIDITY changed.')
        self.reads.append((folder, uid))
        return self.boxes[folder].get(uid)

    def move(self, uv, uid, destination, dest_uv, *, evidence, expires_at, on_prepared):
        require(uv == self.validities['INBOX'] and dest_uv == self.validities[destination], 'Synthetic folder changed.')
        require(self.clock() < expires_at, 'Synthetic approval expired.')
        self.moves.append((uid, destination))
        if self.fault == 'timeout-before':
            raise TimeoutError('synthetic')
        source = self.boxes['INBOX'][uid]
        on_prepared(digest(source.raw))
        target_uid = self.next_uids[destination]
        self.add(replace(source, uid=target_uid), destination)
        if self.fault != 'copy-only':
            del self.boxes['INBOX'][uid]
        if self.fault == 'bad-flags':
            self.boxes[destination][target_uid] = replace(source, uid=target_uid, flags=('\\Seen',))
        if self.fault == 'bad-bytes':
            self.boxes[destination][target_uid] = replace(source, uid=target_uid, raw=b'changed')
        if self.fault == 'timeout-after':
            raise TimeoutError('synthetic')
        if self.fault == 'crash-after':
            raise SimulatedCrash()
        if self.fault == 'missing-mapping':
            return None
        if self.fault == 'wrong-uidvalidity':
            return dest_uv + 1, target_uid
        if self.fault == 'wrong-uid':
            return dest_uv, target_uid + 1
        return dest_uv, target_uid

    def raw_digest(self, folder, uv, uid, size):
        require(self.validities[folder] == uv, 'Synthetic folder changed.')
        return digest(self.boxes[folder][uid].raw)

    def find_exact(self, category, uv, evidence):
        require(self.validities[category] == uv, 'Synthetic destination changed.')
        return [{'uid': m.uid, 'uidvalidity': uv, 'persistent_metadata_matches':
                 all(m.evidence()[k] == evidence[k] for k in ('flags', 'size', 'internaldate'))}
                for m in self.boxes[category].values() if digest(m.raw) == evidence['sha256']]
