"""Snapshot, immutable exact-batch approval, single-attempt moves and reconciliation."""
from __future__ import annotations
import json
import re
import secrets
import time

from .model import CATEGORIES, MAX_PAGE, MAX_RUN, OrganizerError, canonical, digest, integer, require


class Organizer:
    def __init__(self, config, policy, store, mailbox, clock=time.time):
        self.config, self.policy, self.store, self.mailbox, self.clock = config, policy, store, mailbox, clock
        self.scope = config.scope(policy)
        store.verify_identity(config)
        # Never reuse a closed inventory frontier for a different namespace with colliding UIDs.
        if config.principal_binding_sha256:
            with store.db() as db:
                prior=db.execute("SELECT value FROM meta WHERE key='principal_binding'").fetchone()
                require(prior is None or prior[0]==config.principal_binding_sha256, 'Namespace changed; explicit offline reconciliation required.')
                if prior is None:
                    require(not db.execute('SELECT 1 FROM runs LIMIT 1').fetchone(), 'Existing state requires explicit namespace migration.')
                    db.execute("INSERT INTO meta VALUES ('principal_binding',?)",(config.principal_binding_sha256,));db.commit()

    def _scope(self, record):
        self.store.verify_identity(self.config)
        require(record['manifest']['scope'] == self.config.scope(self.policy),
                'Scope or policy changed; reconcile and prepare a fresh review.')

    def _folders(self):
        for category in CATEGORIES:
            require(self.mailbox.folder(category) == self.config.pins[category],
                    'Destination missing or replaced; owner review required.')

    def start_run(self):
        """Explicit invocation only. Repeated calls resume an outstanding run."""
        with self.store.lock():
            with self.store.db() as db:
                require(not db.execute("SELECT 1 FROM attempts WHERE state IN ('attempting','uncertain')").fetchone(), 'Uncertain operations require independent reconciliation.')
                active = db.execute("SELECT id FROM runs WHERE state IN ('scanning','frozen') LIMIT 1").fetchone()
                if active:
                    run = self.store.record('runs', active[0])
                    self._scope(run)
                    return {'run_id': active[0], 'resumed': True, 'initial': bool(run['initial'])}
                require(not db.execute("SELECT 1 FROM attempts WHERE state IN ('attempting','uncertain')").fetchone(),
                        'Uncertain operations require independent reconciliation.')
                metadata = dict(db.execute("SELECT key,value FROM meta WHERE key IN ('uidvalidity','ceiling')"))
            self._folders()
            uv, next_uid = self.mailbox.inbox_identity()
            integer(uv); integer(next_uid)
            initial = 'uidvalidity' not in metadata
            require(initial or int(metadata['uidvalidity']) == uv,
                    'Inbox UIDVALIDITY changed; owner reconciliation required.')
            low, ceiling = (1 if initial else int(metadata['ceiling']) + 1), next_uid - 1
            require(initial or ceiling >= int(metadata['ceiling']), 'Inbox UID frontier regressed.')
            uids = self.mailbox.uids(low, ceiling) if low <= ceiling else []
            require(len(uids) <= MAX_RUN and uids == sorted(set(uids)), 'Snapshot exceeds limits or is invalid.')
            for uid in uids:
                integer(uid, low, ceiling)
            require(self.mailbox.inbox_identity()[0] == uv, 'Inbox changed during enumeration.')
            self.store.ensure_capacity(len(uids), new_run=True)
            key = secrets.token_hex(32)
            manifest = {'scope': self.scope, 'uidvalidity': uv, 'low': low, 'ceiling': ceiling,
                        'uids': uids, 'initial': initial, 'created': self.clock()}
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?)',
                           (key, canonical(manifest), digest(manifest), 'scanning', int(initial), uv, ceiling))
                db.executemany('INSERT INTO items(run_id,uid) VALUES (?,?)', ((key, uid) for uid in uids))
                # Complete UID inventory and frontier committed in the SAME transaction.
                for name, value in [('uidvalidity', uv), ('ceiling', ceiling)]:
                    db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (name, str(value)))
                self.store.event(db, 'snapshot', key, {'count': len(uids), 'initial': initial}, self.clock())
                db.commit()
            return {'run_id': key, 'initial': initial, 'count': len(uids), 'resumed': False}

    def classify_page(self, run_id, limit=10, proposal=None):
        if getattr(self.policy, 'classification_mode', '') == 'client-contextual-proposal-1':
            integer(limit, 1, MAX_PAGE)
            return self._client_classify_page(run_id, proposal)
        require(proposal is None, 'client proposal not supported by this policy.')
        integer(limit, 1, MAX_PAGE)
        with self.store.lock():
            run = self.store.record('runs', run_id)
            self._scope(run)
            require(run['state'] == 'scanning', 'Snapshot already frozen.')
            require(self.mailbox.inbox_identity()[0] == run['uv'], 'Inbox UIDVALIDITY changed.')
            with self.store.db() as db:
                todo = [r[0] for r in db.execute('SELECT uid FROM items WHERE run_id=? AND decision IS NULL ORDER BY uid LIMIT ?',
                                               (run_id, limit))]
            for uid in todo:
                self.store.ensure_capacity()
                # Fetch exceptions do not advance classification. Unsupported mail stays with a reason.
                try:
                    message = self.mailbox.fetch('INBOX', run['uv'], uid)
                    decision = self.policy.classify(message) if message else {
                        'uid': uid, 'category': None, 'reason': 'disappeared', 'customer': False}
                except MessageUnsupported:
                    decision = {'uid': uid, 'category': None, 'reason': 'unreadable-or-oversized', 'customer': False}
                with self.store.db() as db:
                    db.execute('UPDATE items SET decision=? WHERE run_id=? AND uid=? AND decision IS NULL',
                               (canonical(decision), run_id, uid))
                    db.commit()
            return self.run_page(run_id)

    def _client_classify_page(self, run_id, proposal):
        """Read bounded context or validate ONE client submission; never authorizes moves."""
        from .classifier import parse_client_reply
        with self.store.lock():
            run = self.store.record('runs', run_id)
            self._scope(run)
            require(run['state'] == 'scanning', 'Snapshot already frozen.')
            require(self.mailbox.inbox_identity()[0] == run['uv'], 'Inbox UIDVALIDITY changed.')
            if proposal is not None:
                require(type(proposal) is dict and set(proposal) == {
                    'request_id','request_fingerprint','uid','category','customer_risk','reason'},
                    'Exact backend request binding and client classification required.')
                integer(proposal['uid'])
                reply = parse_client_reply({k:proposal[k] for k in ('category','customer_risk','reason')})
                request = self.store.record('classification_requests', proposal['request_id'])
                require(request['run_id'] == run_id and request['uid'] == proposal['uid']
                        and request['fingerprint'] == proposal['request_fingerprint']
                        and request['manifest']['scope'] == self.config.scope(self.policy),
                        'Classification request binding mismatch.')
                submitted = digest(proposal)
                if request['state'] == 'accepted':
                    require(request['submitted_sha256'] == submitted, 'client decision already committed; cannot revise.')
                    result=self.run_page(run_id)  # Exact retry never advances the next UID.
                    result['classification_outcome']={'kind':'client_submission_replayed','uid':request['uid'],'client_classified':True,'requires_client_reply':False,'continue_with_next_message':result['remaining']>0}
                    return result
                require(request['state'] == 'pending', 'Classification request is no longer pending.')
                if request['expires'] <= self.clock():
                    with self.store.db() as db:
                        db.execute("UPDATE classification_requests SET state='expired' WHERE id=?", (request['id'],))
                        db.commit()
                    require(False, 'Classification request expired; request fresh context.')
                current = self.mailbox.fetch('INBOX', run['uv'], request['uid'])
                guard, packet = self.policy.prepare(current) if current else ({}, None)
                if (not self._matching(current, request['manifest']['evidence']) or packet is None
                        or digest(packet) != request['manifest']['packet_sha256']):
                    with self.store.db() as db:
                        db.execute("UPDATE classification_requests SET state='stale' WHERE id=?", (request['id'],))
                        db.commit()
                    require(False, 'Source, flags or protection changed; classification must be reviewed again.')
                decision = self.policy.accept(current, reply, request['id'], request['fingerprint'])
                decision['classification_origin']='client'
                with self.store.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    require(db.execute('UPDATE items SET decision=? WHERE run_id=? AND uid=? AND decision IS NULL',
                                       (canonical(decision), run_id, request['uid'])).rowcount == 1,
                            'Message already classified.')
                    require(db.execute("UPDATE classification_requests SET state='accepted',submitted_sha256=? WHERE id=? AND state='pending'",
                                       (submitted, request['id'])).rowcount == 1, 'Request already consumed.')
                    self.store.event(db, 'client_classified', request['id'], {'uid':request['uid']}, self.clock())
                    db.commit()
                result=self.run_page(run_id)
                result['classification_outcome']={'kind':'client_submission','uid':request['uid'],'client_classified':True,'requires_client_reply':False,'continue_with_next_message':result['remaining']>0,'reason':decision['reason']}
                return result
            with self.store.db() as db:
                row = db.execute('SELECT uid FROM items WHERE run_id=? AND decision IS NULL ORDER BY uid LIMIT 1', (run_id,)).fetchone()
            if row is None:
                return self.run_page(run_id)
            uid = row['uid']
            self.store.ensure_capacity()
            try:
                message = self.mailbox.fetch('INBOX', run['uv'], uid)
                decision, packet = self.policy.prepare(message) if message else ({
                    'uid':uid,'category':None,'reason':'disappeared','customer':False}, None)
            except MessageUnsupported:
                decision, packet = {'uid':uid,'category':None,'reason':'unreadable-or-oversized','customer':False}, None
            if packet is None:
                decision['classification_origin']='organizer'
                with self.store.db() as db:
                    db.execute('UPDATE items SET decision=? WHERE run_id=? AND uid=? AND decision IS NULL',
                               (canonical(decision), run_id, uid))
                    db.execute("UPDATE classification_requests SET state='stale' WHERE run_id=? AND uid=? AND state='pending'", (run_id, uid))
                    db.commit()
                result=self.run_page(run_id)
                result['classification_outcome']={'kind':'automatic_keep','uid':uid,'display_category':'Inbox / Keep','reason':decision['reason'],'client_classified':False,'requires_client_reply':False,'continue_with_next_message':result['remaining']>0}
                return result
            with self.store.db() as db:
                pending = db.execute("SELECT id FROM classification_requests WHERE run_id=? AND uid=? AND state='pending'", (run_id, uid)).fetchone()
                count = db.execute('SELECT count(*) FROM classification_requests WHERE run_id=? AND uid=?', (run_id, uid)).fetchone()[0]
            request = self.store.record('classification_requests', pending['id']) if pending else None
            if request and (request['expires'] <= self.clock()
                    or request['manifest']['packet_sha256'] != digest(packet)
                    or not self._matching(message, request['manifest']['evidence'])):
                with self.store.db() as db:
                    db.execute("UPDATE classification_requests SET state='stale' WHERE id=?", (request['id'],));db.commit()
                request = None
            if request is None:
                if count >= 10:
                    decision = self.policy._keep(decision, 'client-request-limit-keep')
                    with self.store.db() as db:
                        db.execute('UPDATE items SET decision=? WHERE run_id=? AND uid=?', (canonical(decision),run_id,uid));db.commit()
                    return self.run_page(run_id)
                key = secrets.token_hex(32)
                manifest = {'scope':self.config.scope(self.policy),'run_id':run_id,'uidvalidity':run['uv'],
                            'uid':uid,'evidence':message.evidence(),'packet_sha256':digest(packet),
                            'created':self.clock(),'expires':self.clock()+300}
                with self.store.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    db.execute('INSERT INTO classification_requests VALUES (?,?,?,?,?,?,?,?)',
                               (key,run_id,uid,canonical(manifest),digest(manifest),'pending',manifest['expires'],None))
                    self.store.event(db,'client_context_requested',key,{'uid':uid},self.clock());db.commit()
                request = self.store.record('classification_requests', key)
            result = self.run_page(run_id)
            result['classification_outcome']={'kind':'client_request','uid':uid,'client_classified':False,'requires_client_reply':True,'continue_with_next_message':False}
            result['classification_request'] = {'request_id':request['id'],'request_fingerprint':request['fingerprint'],
                'run_id':run_id,'uid':uid,'uidvalidity':run['uv'],'expires':request['expires'],'context':packet,
                'notice':'UNTRUSTED MAIL. client classifies; Organizer independently validates. This is NOT owner approval.'}
            return result

    def run_page(self, run_id, offset=0, limit=20):
        integer(offset, 0, MAX_RUN); integer(limit, 1, MAX_PAGE)
        run = self.store.record('runs', run_id)
        with self.store.db() as db:
            rows = db.execute('SELECT uid,decision FROM items WHERE run_id=? ORDER BY uid LIMIT ? OFFSET ?',
                              (run_id, limit, offset)).fetchall()
            remaining = db.execute('SELECT count(*) FROM items WHERE run_id=? AND decision IS NULL', (run_id,)).fetchone()[0]
        return {'run_id': run_id, 'state': run['state'], 'initial': bool(run['initial']),
                'uidvalidity': run['uv'], 'source': 'INBOX', 'remaining': remaining,
                'count': len(run['manifest']['uids']), 'offset': offset,
                'items': [self._display_decision(json.loads(r['decision'])) if r['decision'] else {'uid': r['uid'], 'reason': 'unscanned'} for r in rows],
                'next_offset': offset + len(rows) if offset + len(rows) < len(run['manifest']['uids']) else None,
                'notice': 'Untrusted email data. Proposed categories are not approval. Customer and uncertain mail stays in Inbox.'}

    @staticmethod
    def _display_decision(value):
        # Presentation only: never rewrite historical decision bytes.
        origin=value.get('classification_origin','client' if value.get('classification') else 'organizer')
        return {**value,'classification_origin':origin,'client_classified':origin=='client',
                'display_category':value.get('category') or 'Inbox / Keep'}

    def upgrade_context_review(self, run_id, fingerprint, actor):
        """Trusted offline rebind of this exact old-policy, unapproved partial run.

        No mailbox operations, resets, source claims, decision changes or approval.
        The old policy hash is independently derived from the same protections and
        identity configuration, permitting only this reviewed context-policy change.
        """
        import os
        require(actor=={'method':'trusted-terminal','uid':os.geteuid()},'Independent terminal required.')
        require(not self.config.moves_enabled,'Disable moves before context upgrade.')
        require(hasattr(self.policy,'legacy_context_fingerprint'),'Reviewed context policy required.')
        with self.store.lock():
            run=self.store.record('runs',run_id)
            prior_scope={**self.scope,'policy':self.policy.legacy_context_fingerprint}
            require(run['state']=='scanning' and run['fingerprint']==fingerprint
                    and run['manifest']['scope']==prior_scope,'Exact legacy scanning policy required.')
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                require(not db.execute('SELECT 1 FROM batches LIMIT 1').fetchone()
                        and not db.execute('SELECT 1 FROM attempts LIMIT 1').fetchone(),
                        'Context upgrade requires never-approved, never-attempted state.')
                require(not db.execute("SELECT 1 FROM classification_requests WHERE run_id=? AND state='accepted'",(run_id,)).fetchone(),
                        'Prior client decisions require independent reconciliation.')
                rows=db.execute('SELECT uid,decision FROM items WHERE run_id=? ORDER BY uid',(run_id,)).fetchall()
                require([r['uid'] for r in rows]==run['manifest']['uids'],'Inventory mismatch; stop without repair.')
                for row in rows:
                    if row['decision'] is not None:
                        d=json.loads(row['decision'])
                        require(d.get('category') is None and not d.get('move_eligible')
                                and not d.get('classification') and d.get('classification_origin','organizer')=='organizer',
                                'Preserve prior client decisions through independent reconciliation.')
                manifest={**run['manifest'],'scope':self.scope,
                          'context_revision':run['manifest'].get('context_revision',0)+1}
                # Preserve all decision strings, UID rows, ceilings, generations and frontier.
                db.execute("UPDATE classification_requests SET state='superseded' WHERE run_id=? AND state='pending'",(run_id,))
                self.store.event(db,'owner-context-review-upgrade',run_id,
                    {'prior_manifest':run['manifest'],'prior_fingerprint':fingerprint,
                     'new_fingerprint':digest(manifest),'actor':actor},self.clock())
                db.execute('UPDATE runs SET manifest=?,fingerprint=? WHERE id=?',
                           (canonical(manifest),digest(manifest),run_id));db.commit()
        return {'run_id':run_id,'inventory_count':len(rows),'moves':0,'approved':False,
                'decisions_preserved':True,'frontier_preserved':True}

    def prepare_batch(self, run_id, keep_uids=None):
        """client can veto any candidate. It cannot invent a destination or weaken protection."""
        keep_uids = [] if keep_uids is None else keep_uids
        require(isinstance(keep_uids, list) and len(keep_uids) <= MAX_RUN, 'Invalid conservative exclusions.')
        for uid in keep_uids:
            integer(uid)
        with self.store.lock():
            run = self.store.record('runs', run_id)
            self._scope(run)
            with self.store.db() as db:
                old = db.execute("SELECT id FROM batches WHERE run_id=? AND state IN ('pending','approved','executing','uncertain') ORDER BY rowid DESC LIMIT 1", (run_id,)).fetchone()
                require(not db.execute("SELECT 1 FROM attempts WHERE state IN ('attempting','uncertain')").fetchone(), 'Uncertain operations require independent reconciliation.')
                if old:
                    require(not keep_uids, 'Frozen batch cannot be edited.')
                    return self.batch_status(old[0])
                rows = db.execute('SELECT uid,decision FROM items WHERE run_id=? ORDER BY uid', (run_id,)).fetchall()
            require(run['state'] in ('scanning','frozen','closed') and all(r['decision'] for r in rows), 'Finish complete snapshot classification first.')
            require(set(keep_uids) <= set(run['manifest']['uids']), 'Exclusion outside snapshot.')
            decisions = [json.loads(r['decision']) for r in rows]
            for d in decisions:
                if d['uid'] in keep_uids:
                    d.update(category=None, reason='client-conservative-veto')
            with self.store.db() as db:
                assigned, generations = self._assigned(db, run_id)
                vetoes={r['uid'] for r in db.execute('SELECT uid FROM inventory_vetoes WHERE run_id=?',(run_id,))} | set(keep_uids)
                prior = db.execute('SELECT id FROM batches WHERE run_id=? ORDER BY rowid DESC LIMIT 1',(run_id,)).fetchone()
            candidates = [d for d in decisions if d.get('category') in CATEGORIES and not d.get('customer')
                          and d['uid'] not in vetoes and (d['uid'],generations.get(d['uid'],0)) not in assigned]
            if not candidates and prior:
                require(not keep_uids, 'Frozen batches cannot be edited.')
                return self.batch_status(prior['id'])
            moves=[]; deferred=[]
            for d in candidates:
                if len(moves)>=self.config.max_batch_moves:break
                if hasattr(self.policy, 'revalidate'):
                    current = self.mailbox.fetch('INBOX', run['uv'], d['uid'])
                    checked = self.policy.revalidate(current, d) if current else {}
                    if checked.get('category') != d['category'] or checked.get('rule_ids') != d.get('rule_ids'):
                        deferred.append(d['uid']);continue
                if getattr(self.policy,'mode','')=='practical':
                    d={**d,'source_integrity':self._integrity_snapshot(run['uv'],d)}
                moves.append(d)
            require(moves or not candidates, 'Evidence/source review required; no fresh eligible batch.')
            self._folders()
            expires = self.clock() + self.config.approval_seconds
            if moves and getattr(self.policy, 'evidence_source', None) is not None:
                expires = min(expires, *(d['authentication']['expires_at'] for d in moves))
                require(expires > self.clock(), 'Authentication proof expired.')
            self.store.ensure_capacity()
            manifest = {'scope': self.scope, 'run_id': run_id, 'run_fingerprint': run['fingerprint'],
                        'uidvalidity': run['uv'], 'initial': bool(run['initial']), 'decisions': decisions,
                        'moves': moves, 'review_generations': {str(d['uid']):generations.get(d['uid'],0) for d in moves},
                        'deferred_review_uids':deferred, 'inventory_fingerprint':run['fingerprint'],
                        'moves_remaining_unbatched':len(candidates)-len(moves), 'created': self.clock(), 'expires': expires, 'move_count': len(moves)}
            key = secrets.token_hex(32)
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                db.executemany('INSERT OR IGNORE INTO inventory_vetoes VALUES (?,?)',((run_id,u) for u in keep_uids))
                db.execute('INSERT INTO batches VALUES (?,?,?,?,?,?,?,?)',
                           (key, run_id, canonical(manifest), digest(manifest), 'pending' if moves else 'completed', expires, None, None))
                db.execute('UPDATE runs SET state=? WHERE id=?', ('frozen' if moves else 'closed', run_id))
                self.store.event(db, 'prepared', key, {'moves': len(moves)}, self.clock())
                db.commit()
            return self.batch_status(key)

    def batch_status(self, batch_id):
        # Historical receipts remain readable after expiry, policy change or moves-disabled.
        batch = self.store.record('batches', batch_id)
        with self.store.db() as db:
            rows = db.execute('SELECT uid,state,result FROM attempts WHERE batch_id=? ORDER BY uid', (batch_id,)).fetchall()
        return {'batch_id': batch_id, 'run_id': batch['run_id'], 'state': batch['state'],
                'fingerprint': batch['fingerprint'], 'expires': batch['expires'],
                'expired': batch['expires'] <= self.clock(), 'move_count': batch['manifest']['move_count'],
                'receipts': [{'uid': r['uid'], 'state': r['state'], 'result': json.loads(r['result']) if r['result'] else None} for r in rows]}

    def decide(self, batch_id, fingerprint, approve, actor):
        """Trusted-terminal API ONLY. Never expose this method via MCP or client IPC."""
        require(type(approve) is bool and actor == {'method': 'trusted-terminal', 'uid': __import__('os').geteuid()},
                'Independent terminal approval required.')
        with self.store.lock():
            batch = self.store.record('batches', batch_id)
            self._scope(batch)
            require(fingerprint == batch['fingerprint'], 'Approval fingerprint mismatch.')
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                changed = db.execute("UPDATE batches SET state=?,actor=?,decided=? WHERE id=? AND state='pending' AND fingerprint=? AND expires>?",
                                     ('approved' if approve else 'rejected', canonical(actor), self.clock(),
                                      batch_id, fingerprint, self.clock())).rowcount
                require(changed == 1, 'Batch expired or already decided.')
                if not approve:
                    self._refresh_run(db, batch['run_id'])
                self.store.event(db, 'approved' if approve else 'rejected', batch_id,
                                 {'fingerprint': fingerprint, 'actor': actor}, self.clock())
                db.commit()
        return self.batch_status(batch_id)

    def _source_key(self, uv, uid):
        return digest({'host': self.config.host, 'account': self.config.account, 'mailbox': 'INBOX', 'uidvalidity': uv, 'uid': uid})

    def _matching(self, message, evidence):
        return message is not None and all(message.evidence()[k] == evidence[k]
                                          for k in ('uid', 'sha256', 'size', 'flags', 'internaldate', 'identity_kind'))

    def _integrity_snapshot(self,uv,evidence):
        require(self.mailbox.inbox_identity()[0]==uv,'Source UIDVALIDITY changed before snapshot.')
        current=self.mailbox.fetch('INBOX',uv,evidence['uid'])
        require(self._matching(current,evidence),'Source changed before exact batch review.')
        raw=self.mailbox.raw_digest('INBOX',uv,evidence['uid'],evidence['size'])
        require(type(raw) is str and re.fullmatch(r'[0-9a-f]{64}',raw),'Source digest unavailable.')
        require(self._matching(self.mailbox.fetch('INBOX',uv,evidence['uid']),evidence),'Source changed during integrity snapshot.')
        require(self.mailbox.inbox_identity()[0]==uv,'Source UIDVALIDITY changed during snapshot.')
        return {'kind':'source-integrity-v1','host':self.config.host,'account':self.config.account,
                'namespace':self.config.principal_binding_sha256,'uidvalidity':uv,'uid':evidence['uid'],
                'view_sha256':evidence['sha256'],'size':evidence['size'],'flags':evidence['flags'],
                'internaldate':evidence['internaldate'],'classification_sha256':digest(evidence['classification']),
                'policy':self.policy.fingerprint,'raw_sha256':raw}

    def execute(self, batch_id, uid):
        """One explicitly named UID per invocation; retries cannot advance to another message."""
        integer(uid)
        require(self.config.moves_enabled, 'Organizer moves are disabled.')
        with self.store.lock():
            batch = self.store.record('batches', batch_id)
            if batch['state'] in ('completed', 'uncertain', 'blocked', 'rejected', 'expired', 'cancelled'):
                return self.batch_status(batch_id)
            self._scope(batch)
            require(batch['state'] in ('approved', 'executing') and batch['actor'], 'Independent exact-batch approval required.')
            if batch['expires'] <= self.clock():
                self._close(batch, 'expired')
                return self.batch_status(batch_id)
            self._folders()
            require(self.mailbox.inbox_identity()[0] == batch['manifest']['uidvalidity'], 'Inbox UIDVALIDITY changed.')
            selected = [e for e in batch['manifest']['moves'] if e['uid'] == uid]
            require(len(selected) == 1, 'UID is not in this approved move batch.')
            for evidence in selected:
                uid, uv = evidence['uid'], batch['manifest']['uidvalidity']
                source_key = self._source_key(uv, uid)
                with self.store.db() as db:
                    old = db.execute('SELECT state,batch_id FROM attempts WHERE source_key=?', (source_key,)).fetchone()
                    unresolved = db.execute("SELECT 1 FROM attempts WHERE state IN ('attempting','uncertain')").fetchone()
                if old:
                    if old['state'] == 'verified' and old['batch_id'] == batch_id:
                        return self.batch_status(batch_id)
                    self._close(batch, 'uncertain' if old['state'] in ('attempting', 'uncertain') else 'blocked')
                    return self.batch_status(batch_id)
                require(not unresolved, 'Account has an unresolved operation.')
                # Preflight is non-marking and before the durable network-write claim.
                current = self.mailbox.fetch('INBOX', uv, uid)
                decision = ((self.policy.revalidate(current, evidence) if hasattr(self.policy, 'revalidate')
                             else self.policy.classify(current)) if current else {})
                if (not self._matching(current, evidence) or decision.get('category') != evidence['category']
                        or decision.get('customer') or decision.get('rule_ids') != evidence.get('rule_ids')):
                    self._close(batch, 'blocked')
                    return self.batch_status(batch_id)
                if getattr(self.policy,'mode','')=='practical':
                    try:
                        require(evidence.get('source_integrity')==self._integrity_snapshot(uv,evidence),
                                'Approved source integrity changed.')
                    except Exception:
                        self._close(batch,'blocked');return self.batch_status(batch_id)
                self._folders()
                if self.clock() >= batch['expires']:
                    self._close(batch, 'expired')
                    return self.batch_status(batch_id)
                self.store.ensure_capacity()
                with self.store.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    db.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?)',
                               (source_key, batch_id, uid, 'attempting', canonical(evidence), None,
                                self.clock(), self.clock()))
                    db.execute("UPDATE batches SET state='executing' WHERE id=?", (batch_id,))
                    self.store.event(db, 'claimed', source_key, {'batch_id': batch_id, 'uid': uid}, self.clock())
                    db.commit()  # MUST precede every possible wire mutation.
                try:
                    destination = evidence['category']
                    dest_uv = self.config.pins[destination]
                    def prepared(raw_sha256):
                        require(isinstance(raw_sha256, str) and len(raw_sha256) == 64
                                and all(c in '0123456789abcdef' for c in raw_sha256), 'Invalid source verification digest.')
                        if getattr(self.policy, 'evidence_source', None) is not None:
                            require(raw_sha256 == evidence['authentication']['rfc822_sha256']
                                    and self.clock() < evidence['authentication']['expires_at'],
                                    'Approved authentication proof no longer binds source bytes.')
                        if getattr(self.policy,'mode','')=='practical':
                            require(raw_sha256==evidence['source_integrity']['raw_sha256'],
                                    'Approved source bytes changed before MOVE.')
                        with self.store.db() as db:
                            db.execute("UPDATE attempts SET result=?,updated=? WHERE source_key=? AND state='attempting'",
                                       (canonical({'source_raw_sha256': raw_sha256}), self.clock(), source_key))
                            db.commit()
                    mapped_uv, dest_uid = self.mailbox.move(uv, uid, destination, dest_uv,
                                                          evidence=evidence, expires_at=batch['expires'], on_prepared=prepared)
                    integer(mapped_uv); integer(dest_uid)
                    require(mapped_uv == dest_uv, 'Destination identity changed.')
                    mapping = {'destination': destination, 'uidvalidity': dest_uv, 'uid': dest_uid}
                    with self.store.db() as db:
                        old_result = db.execute('SELECT result FROM attempts WHERE source_key=?', (source_key,)).fetchone()
                        prepared_receipt = json.loads(old_result[0]) if old_result and old_result[0] else {}
                        require('source_raw_sha256' in prepared_receipt, 'Source verification receipt missing.')
                        db.execute("UPDATE attempts SET result=?,updated=? WHERE source_key=? AND state='attempting'",
                                   (canonical({**prepared_receipt, 'acknowledged_mapping': mapping}), self.clock(), source_key))
                        db.commit()
                    after = self.mailbox.fetch(destination, dest_uv, dest_uid)
                    expected = {**evidence, 'uid': dest_uid}
                    require(self._matching(after, expected), 'Destination verification failed.')
                    require(self.mailbox.raw_digest(destination, dest_uv, dest_uid, evidence['size'])
                            == prepared_receipt['source_raw_sha256'], 'Destination bytes changed.')
                    require(self.mailbox.fetch('INBOX', uv, uid) is None, 'Source still exists.')
                    require(self.mailbox.folder(destination) == dest_uv, 'Destination changed after move.')
                    self._finish(source_key, 'verified', {'destination': destination, 'uidvalidity': dest_uv,
                                                         'uid': dest_uid, 'sha256': evidence['sha256'],
                                                         'source_raw_sha256': prepared_receipt['source_raw_sha256']})
                except Exception:
                    # Includes definitive-looking rejection: MOVE can partly succeed. No automatic retry.
                    with self.store.db() as db:
                        row = db.execute('SELECT result FROM attempts WHERE source_key=?', (source_key,)).fetchone()
                        prior = json.loads(row[0]) if row and row[0] else {}
                    self._finish(source_key, 'uncertain', {**prior, 'retry_allowed': False, 'reason': 'reconcile-independently'})
                    self._close(batch, 'uncertain')
                    return self.batch_status(batch_id)
            with self.store.db() as db:
                verified = db.execute("SELECT count(*) FROM attempts WHERE batch_id=? AND state='verified'", (batch_id,)).fetchone()[0]
            if verified == batch['manifest']['move_count']:
                self._close(batch, 'completed')
            return self.batch_status(batch_id)

    def _assigned(self, db, run_id):
        generations={r['uid']:r['generation'] for r in db.execute('SELECT uid,generation FROM item_generations WHERE run_id=?',(run_id,))}
        assigned=set()
        for row in db.execute('SELECT manifest FROM batches WHERE run_id=?',(run_id,)):
            manifest=json.loads(row['manifest'])
            for d in manifest['moves']:
                assigned.add((d['uid'],manifest.get('review_generations',{}).get(str(d['uid']),0)))
        return assigned,generations

    def _refresh_run(self, db, run_id):
        assigned,generations=self._assigned(db,run_id)
        vetoes={r['uid'] for r in db.execute('SELECT uid FROM inventory_vetoes WHERE run_id=?',(run_id,))}
        remaining=False
        for row in db.execute('SELECT uid,decision FROM items WHERE run_id=?',(run_id,)):
            d=json.loads(row['decision']) if row['decision'] else None
            if d is None or (d.get('category') in CATEGORIES and not d.get('customer') and row['uid'] not in vetoes and (row['uid'],generations.get(row['uid'],0)) not in assigned):remaining=True
        active=db.execute("SELECT 1 FROM batches WHERE run_id=? AND state IN ('pending','approved','executing','uncertain')",(run_id,)).fetchone()
        db.execute('UPDATE runs SET state=? WHERE id=?',('frozen' if remaining or active else 'closed',run_id))

    def renew_review(self, run_id, fingerprint, uids, actor):
        """Trusted owner only: revoke no approval implicitly; keep immutable history and source claims."""
        import os
        require(actor=={'method':'trusted-terminal','uid':os.geteuid()},'Independent terminal required.')
        require(type(uids) is list and 0<len(uids)<=500 and len(set(uids))==len(uids),'Bounded exact review selection required.')
        for uid in uids:integer(uid)
        with self.store.lock():
            run=self.store.record('runs',run_id)
            require(run['fingerprint']==fingerprint and set(uids)<=set(run['manifest']['uids']),'Review inventory mismatch.')
            require(run['manifest']['scope']['account']==self.config.account and run['manifest']['scope']['host']==self.config.host,'Account changed.')
            require(self.mailbox.inbox_identity()[0]==run['uv'],'Inbox UIDVALIDITY changed.')
            with self.store.db() as db:
                require(not db.execute("SELECT 1 FROM attempts WHERE state IN ('attempting','uncertain')").fetchone(),'Reconcile uncertainty first.')
                require(not db.execute("SELECT 1 FROM batches WHERE run_id=? AND state IN ('pending','approved','executing','uncertain')",(run_id,)).fetchone(),'Cancel or retire every outstanding batch before re-review.')
                for uid in uids:
                    require(not db.execute('SELECT 1 FROM attempts WHERE source_key=?',(self._source_key(run['uv'],uid),)).fetchone(),'Claimed sources cannot be renewed or retried.')
            # Renewal can issue fresh unapproved proof evidence, never authorization.
            evidence=getattr(self.policy,'evidence_source',None)
            if evidence is not None:
                require(hasattr(evidence,'renew'),'Evidence source cannot renew safely.')
                for uid in uids:evidence.renew(run['uv'],uid)
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                for uid in uids:
                    row=db.execute('SELECT decision FROM items WHERE run_id=? AND uid=?',(run_id,uid)).fetchone()
                    require(row is not None,'Inventory row missing.')
                    db.execute('INSERT INTO decision_history(run_id,uid,prior_decision,prior_manifest,at) VALUES (?,?,?,?,?)',(run_id,uid,row['decision'] or 'null',canonical(run['manifest']),self.clock()))
                    db.execute('INSERT INTO item_generations VALUES (?,?,1) ON CONFLICT(run_id,uid) DO UPDATE SET generation=generation+1',(run_id,uid))
                    db.execute('UPDATE items SET decision=NULL WHERE run_id=? AND uid=?',(run_id,uid))
                    db.execute("UPDATE classification_requests SET state='superseded' WHERE run_id=? AND uid=?",(run_id,uid))
                manifest={**run['manifest'],'scope':self.config.scope(self.policy),'review_revision':run['manifest'].get('review_revision',0)+1}
                db.execute("UPDATE runs SET manifest=?,fingerprint=?,state='scanning' WHERE id=?",(canonical(manifest),digest(manifest),run_id))
                self.store.event(db,'owner-renewed-review',run_id,{'uids':uids,'prior_fingerprint':fingerprint,'new_fingerprint':digest(manifest),'actor':actor},self.clock());db.commit()
        return self.run_page(run_id)

    def _finish(self, source_key, state, result):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE attempts SET state=?,result=?,updated=? WHERE source_key=? AND state='attempting'",
                                 (state, canonical(result), self.clock(), source_key)).rowcount
            require(changed == 1, 'Attempt already finalized.')
            self.store.event(db, state, source_key, result, self.clock())
            db.commit()

    def _close(self, batch, state):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE batches SET state=? WHERE id=?', (state, batch['id']))
            self._refresh_run(db, batch['run_id'])
            self.store.event(db, state, batch['id'], {}, self.clock())
            db.commit()

    def reconcile(self, batch_id):
        """Trusted diagnostic. No mailbox writes, retries, repairs or claim resets."""
        batch = self.store.record('batches', batch_id)
        self._scope(batch)
        with self.store.lock(), self.store.db() as db:
            attempts = db.execute("SELECT * FROM attempts WHERE batch_id=? AND state IN ('attempting','uncertain')", (batch_id,)).fetchall()
            observations = []
            for attempt in attempts:
                evidence = json.loads(attempt['evidence'])
                uv, uid = batch['manifest']['uidvalidity'], attempt['uid']
                self._folders()
                require(self.mailbox.inbox_identity()[0] == uv, 'Identity changed; stop reconciliation.')
                source = self.mailbox.fetch('INBOX', uv, uid)
                # Bounded full-content candidate search, NEVER Message-ID alone.
                candidates = self.mailbox.find_exact(evidence['category'], self.config.pins[evidence['category']], evidence)
                result = {'uid': uid, 'source_present': source is not None,
                          'source_matches': self._matching(source, evidence), 'destination_candidates': candidates,
                          'retry_allowed': False, 'decision': 'owner-investigation-required'}
                receipt = json.loads(attempt['result']) if attempt['result'] else {}
                result['acknowledged_mapping'] = receipt.get('acknowledged_mapping')
                observations.append(result)
            return {'batch_id': batch_id, 'observations': observations, 'writes': 0,
                    'notice': 'Candidate equality does not establish unique MOVE provenance. No claim is cleared.'}

    def abandon_uncertain(self, batch_id, fingerprint, actor):
        """Independent owner may close uncertainty WITHOUT retry eligibility or mailbox changes."""
        import os
        require(actor == {'method': 'trusted-terminal', 'uid': os.geteuid()}, 'Independent terminal required.')
        with self.store.lock():
            batch = self.store.record('batches', batch_id)
            require(batch['fingerprint'] == fingerprint, 'Abandonment fingerprint mismatch.')
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                rows = db.execute("SELECT source_key,result FROM attempts WHERE batch_id=? AND state IN ('attempting','uncertain')",
                                  (batch_id,)).fetchall()
                require(bool(rows), 'No uncertain attempt to abandon.')
                for row in rows:
                    receipt = json.loads(row['result']) if row['result'] else {}
                    receipt.update(retry_allowed=False, owner_abandoned=True)
                    db.execute("UPDATE attempts SET state='abandoned',result=?,updated=? WHERE source_key=?",
                               (canonical(receipt), self.clock(), row['source_key']))
                db.execute("UPDATE batches SET state='blocked' WHERE id=?", (batch_id,))
                self._refresh_run(db, batch['run_id'])
                self.store.event(db, 'owner-abandoned-no-retry', batch_id,
                                 {'fingerprint': fingerprint, 'actor': actor, 'count': len(rows)}, self.clock())
                db.commit()
        return self.batch_status(batch_id)

    def retire_expired(self, batch_id):
        """Close an expired unconsumed remainder. Receipts and source tombstones survive."""
        with self.store.lock():
            batch = self.store.record('batches', batch_id)
            require(batch['expires'] <= self.clock(), 'Batch is not expired.')
            with self.store.db() as db:
                require(not db.execute("SELECT 1 FROM attempts WHERE batch_id=? AND state IN ('attempting','uncertain')",
                                       (batch_id,)).fetchone(), 'Reconcile uncertainty first.')
            if batch['state'] in ('pending', 'approved', 'executing'):
                self._close(batch, 'expired')
        return self.batch_status(batch_id)

    def cancel_batch(self, batch_id, fingerprint, actor):
        """Trusted owner revocation: stop the unclaimed remainder, never reverse or reset attempts."""
        import os
        require(actor == {'method': 'trusted-terminal', 'uid': os.geteuid()}, 'Independent terminal required.')
        with self.store.lock():
            batch = self.store.record('batches', batch_id)
            require(batch['fingerprint'] == fingerprint, 'Cancellation fingerprint mismatch.')
            require(batch['state'] in ('pending', 'approved', 'executing'), 'Batch cannot be cancelled; inspect receipts.')
            with self.store.db() as db:
                require(not db.execute("SELECT 1 FROM attempts WHERE batch_id=? AND state IN ('attempting','uncertain')",
                                       (batch_id,)).fetchone(), 'Reconcile uncertain attempts first.')
            self._close(batch, 'cancelled')
            with self.store.db() as db:
                self.store.event(db, 'owner-cancelled', batch_id, {'fingerprint': fingerprint, 'actor': actor}, self.clock())
                db.commit()
        return self.batch_status(batch_id)


class MessageUnsupported(OrganizerError):
    pass
