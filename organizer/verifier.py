"""Protected read-only DKIM evidence service. Never an MCP tool or approval authority.

Pinned public key snapshots are operator trust anchors, not mail-provided claims.
No online DNS or delivery-time/SPF/ARC/SASL provenance is asserted by this candidate.
"""
from dataclasses import replace
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time

from .imap_adapter import GuardedIMAP, IMAPMailbox, CHUNK, MAX_MESSAGE_SIZE
from .ipc import Broker, Client
from .model import canonical, digest, integer, persistent, require
from .store import Store

class SilentCryptoLog:
    def debug(self,*args,**kwargs):pass
    info=warning=error=critical=exception=debug


VERSION = 'stored-dkim-strict-pin-v1'
HEX = re.compile(r'[0-9a-f]{64}')
DOMAIN = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+')
# Even absent headers are oversigned, so unsigned insertion cannot alter protections.
COVERED = ('from','sender','reply-to','to','cc','subject','date','message-id',
           'references','in-reply-to','list-id','content-type','content-transfer-encoding','mime-version')
FIELDS = {'proof_id','version','host','account','mailbox','uidvalidity','uid','view_sha256',
          'view_algorithm','rfc822_sha256','rfc822_size','flags','internaldate',
          'aligned_domain','signed_headers','key_policy_sha256','verified_at','expires_at'}


class ReadOnlyIMAP(GuardedIMAP):
    def _command(self, name, *args):
        require(name not in ('SELECT','LIST') and not (name == 'UID' and args and args[0] != 'FETCH'),
                'Verifier command prohibited.')
        if name in ('EXAMINE','MYRIGHTS'):
            require(args == (getattr(self,'_namespace_names',{}).get('INBOX','"INBOX"'),), 'Verifier only reads INBOX.')
        return super()._command(name, *args)


class VerificationMailbox(IMAPMailbox):
    """Separate credential identity; no backend/Reader secret is loaded here."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, client_factory=ReadOnlyIMAP, **kwargs)

    def snapshot(self, uv, uid):
        integer(uv); integer(uid)
        with self.connection() as c:
            self._identity(c, 'INBOX', uv)
            self._rights(c, 'INBOX', 'lr')
            before = self._fetch(c, uid)
            require(before is not None and before.view is not None, 'No verifiable source.')
            size = before.view.source_size
            require(0 < size <= min(MAX_MESSAGE_SIZE, 8*1024*1024), 'Verifier source limit.')
            raw = bytearray(); deadline=time.monotonic()+20
            for offset in range(0,size,CHUNK):
                require(time.monotonic()<deadline, 'Verifier snapshot deadline.')
                count=min(CHUNK,size-offset)
                item='(UID BODY.PEEK[]<'+str(offset)+'.'+str(count)+'>)'
                c._raw_permit=(str(uid),item)
                raw.extend(self._literal(c,uid,item,'',count,offset))
            after=self._fetch(c,uid)
            self._identity(c,'INBOX',uv)
            require(after is not None and before.evidence()==after.evidence(), 'Source changed during verification.')
            return replace(before,source_uidvalidity=uv),bytes(raw)


class PinnedKeys:
    """Bounded operator-supplied public key snapshot. No network or mail key discovery."""
    def __init__(self, values, clock=time.time):
        require(type(values) is dict and set(values)=={'version','expires_at','records'}
                and values['version']==1 and type(values['expires_at']) in (int,float)
                and clock()<values['expires_at']<=clock()+86400, 'Expired/invalid key snapshot.')
        require(type(values['records']) is dict and 0<=len(values['records'])<=500, 'Invalid key snapshot.')
        for name,record in values['records'].items():
            require(type(name) is str and re.fullmatch(r'[a-z0-9_-]{1,63}\._domainkey\.[a-z0-9.-]{1,253}',name)
                    and type(record) is str and len(record)<=4096 and record.startswith('v=DKIM1;')
                    and '\n' not in record and '\r' not in record, 'Invalid public key record.')
        self.values,self.clock=values,clock
        self.fingerprint=digest(values)

    def check_current(self):
        guard=getattr(self,'source_guard',None)
        if guard is not None:require(guard()==self.fingerprint,'Key snapshot changed; operator restart/re-review required.')
        require(self.clock()<self.values['expires_at'],'Key snapshot expired.')

    def dns(self,name,timeout=5):
        self.check_current()
        key=name.decode('ascii').rstrip('.').casefold()
        record=self.values['records'].get(key)
        return record.encode('ascii') if record else None

    def verify(self,raw):
        import dkim
        require(type(raw) is bytes and 0<len(raw)<=8*1024*1024, 'Message limit.')
        header=raw.split(b'\r\n\r\n',1)[0]
        require(len(header)<=65536 and b'\r\n\r\n' in raw, 'Unsupported wire format.')
        msg=BytesParser(policy=policy.default).parsebytes(raw,headersonly=True)
        require(not msg.defects and not msg.get_all('Bcc',[]), 'Ambiguous or unsupported hidden recipients.')
        for name in COVERED:
            require(len(msg.get_all(name,[]))<=1, 'Duplicate classification header.')
        require(not any(n.casefold().startswith('resent-') for n in msg.keys()), 'Forwarded identity unsupported.')
        froms=getaddresses([str(msg.get('From',''))])
        require(len(froms)==1 and froms[0][1].count('@')==1 and not getattr(msg.get('From'),'defects',()), 'Ambiguous From.')
        domain=froms[0][1].rsplit('@',1)[1].casefold()
        require(DOMAIN.fullmatch(domain), 'Unsupported domain.')
        signatures=msg.get_all('DKIM-Signature',[])
        require(len(signatures)==1, 'Exactly one supported signature required.')
        tags=dkim.util.parse_tag_value(str(signatures[0]).encode('ascii'))
        require(tags.get(b'a')==b'rsa-sha256' and b'l' not in tags and tags.get(b'd',b'').decode('ascii').casefold()==domain,
                'Full-body strict domain alignment required.')
        names=[n.strip().decode('ascii').casefold() for n in tags.get(b'h',b'').split(b':')]
        require(set(COVERED)<=set(names) and len(names)<=128, 'Classification headers must be signed/oversigned.')
        if b'x' in tags: require(int(tags[b'x'])>self.clock(), 'Expired signature.')
        if b't' in tags: require(int(tags[b't'])<=self.clock()+60, 'Future signature.')
        require(dkim.DKIM(raw,minkey=2048,logger=SilentCryptoLog()).verify(dnsfunc=self.dns), 'Cryptographic verification failed.')
        return domain


def validate_proof(proof,message,host,account,key_policy_sha256,clock=time.time,namespace_sha256=''):
    fields=FIELDS | ({'namespace_sha256'} if namespace_sha256 else set())
    require(type(proof) is dict and set(proof)==fields and (not namespace_sha256 or proof['namespace_sha256']==namespace_sha256), 'Invalid evidence record or namespace.')
    now=clock(); evidence=message.evidence()
    require(proof['version']==VERSION and proof['host']==host and proof['account']==account
            and proof['mailbox']=='INBOX' and proof['uid']==message.uid
            and proof['uidvalidity']==message.source_uidvalidity and message.source_uidvalidity>0
            and proof['view_algorithm']==evidence['identity_kind']
            and proof['view_sha256']==evidence['sha256'] and proof['rfc822_size']==evidence['size']
            and proof['flags']==evidence['flags'] and proof['internaldate']==evidence['internaldate']
            and proof['key_policy_sha256']==key_policy_sha256
            and type(proof['verified_at']) in (int,float) and type(proof['expires_at']) in (int,float)
            and proof['verified_at']<=now<proof['expires_at']<=proof['verified_at']+900
            and all(type(proof[k]) is str and HEX.fullmatch(proof[k]) for k in ('proof_id','rfc822_sha256','view_sha256','key_policy_sha256'))
            and DOMAIN.fullmatch(proof['aligned_domain']) and proof['signed_headers']==list(COVERED), 'Evidence mismatch or expiry.')
    return proof


class EvidenceVerifier:
    def __init__(self,host,account,mailbox,ledger,keys,clock=time.time):
        self.host,self.account,self.mailbox,self.ledger,self.keys,self.clock=host,account,mailbox,ledger,keys,clock
        self.namespace_sha256=getattr(mailbox,'namespace_sha256','')
        with ledger.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS authentication_proofs (source TEXT PRIMARY KEY, record TEXT NOT NULL)')
            db.commit()

    def renew(self,uv,uid):
        """Only protected backend/operator path; supersede proof without deleting history."""
        self.keys.check_current()
        integer(uv);integer(uid)
        source=digest({'host':self.host,'account':self.account,'mailbox':'INBOX','uv':uv,'uid':uid,'key_policy':self.keys.fingerprint,**({'namespace':self.namespace_sha256} if self.namespace_sha256 else {})})
        with self.ledger.lock(), self.ledger.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS proof_history (seq INTEGER PRIMARY KEY AUTOINCREMENT,source TEXT NOT NULL,record TEXT NOT NULL,at REAL NOT NULL)')
            row=db.execute('SELECT record FROM authentication_proofs WHERE source=?',(source,)).fetchone()
            if row:
                db.execute('INSERT INTO proof_history(source,record,at) VALUES (?,?,?)',(source,row['record'],self.clock()))
                db.execute('DELETE FROM authentication_proofs WHERE source=?',(source,))
            db.commit()
        # Failure leaves no usable current proof; history and source claims survive.
        return self.lookup(uv,uid)

    def lookup(self,uv,uid):
        self.keys.check_current()
        integer(uv);integer(uid)
        source=digest({'host':self.host,'account':self.account,'mailbox':'INBOX','uv':uv,'uid':uid,'key_policy':self.keys.fingerprint,**({'namespace':self.namespace_sha256} if self.namespace_sha256 else {})})
        with self.ledger.lock():
            with self.ledger.db() as db:
                row=db.execute('SELECT record FROM authentication_proofs WHERE source=?',(source,)).fetchone()
                if row:
                    proof=json.loads(row[0])
                    # Never silently refresh behind an approved proof or re-use after expiry.
                    require(self.clock()<proof['expires_at'], 'Proof expired; operator renewal required.')
                    message,raw=self.mailbox.snapshot(uv,uid)
                    require(hashlib.sha256(raw).hexdigest()==proof['rfc822_sha256'], 'Stored proof bytes changed.')
                    validate_proof(proof,message,self.host,self.account,self.keys.fingerprint,self.clock,self.namespace_sha256)
                    return proof
                require(db.execute('SELECT COUNT(*) FROM authentication_proofs').fetchone()[0]<10000, 'Proof capacity reached.')
            message,raw=self.mailbox.snapshot(uv,uid)
            require(message.source_uidvalidity==uv and message.uid==uid and message.view is not None, 'Snapshot identity mismatch.')
            domain=self.keys.verify(raw)
            signature=BytesParser(policy=policy.default).parsebytes(raw,headersonly=True)['DKIM-Signature']
            import dkim
            signature_tags=dkim.util.parse_tag_value(str(signature).encode('ascii'))
            signature_expires=int(signature_tags[b'x']) if b'x' in signature_tags else self.clock()+900
            e=message.evidence();now=self.clock()
            proof={'proof_id':secrets.token_hex(32),'version':VERSION,'host':self.host,'account':self.account,
                'mailbox':'INBOX','uidvalidity':uv,'uid':uid,'view_sha256':e['sha256'],'view_algorithm':e['identity_kind'],
                'rfc822_sha256':hashlib.sha256(raw).hexdigest(),'rfc822_size':len(raw),'flags':e['flags'],
                'internaldate':e['internaldate'],'aligned_domain':domain,'signed_headers':list(COVERED),
                'key_policy_sha256':self.keys.fingerprint,'verified_at':now,
                'expires_at':min(now+900,self.keys.values['expires_at'],signature_expires)}
            if self.namespace_sha256: proof['namespace_sha256']=self.namespace_sha256
            validate_proof(proof,message,self.host,self.account,self.keys.fingerprint,self.clock,self.namespace_sha256)
            self.ledger.ensure_capacity()
            with self.ledger.db() as db:
                db.execute('INSERT INTO authentication_proofs VALUES (?,?)',(source,canonical(proof)));db.commit()
            return proof


class MissingEvidence:
    scope={'kind':'protected-evidence-required-unconfigured-v1'}
    def lookup(self,message):return None


class ProofClient:
    def __init__(self,path,verifier_uid,host,account,key_policy_sha256,clock=time.time,namespace_sha256=''):
        require(type(key_policy_sha256) is str and HEX.fullmatch(key_policy_sha256),'Key policy pin required.')
        self.namespace_sha256=namespace_sha256
        require(not namespace_sha256 or HEX.fullmatch(namespace_sha256), 'Namespace pin required.')
        self.client=Client(path,verifier_uid)
        self.host,self.account,self.key_policy_sha256,self.clock=host,account,key_policy_sha256,clock
        self.scope={'version':VERSION,'host':host,'account':account,'key_policy_sha256':key_policy_sha256,
                    'verifier_uid':verifier_uid,'socket':str(path),**({'namespace_sha256':namespace_sha256} if namespace_sha256 else {})}
    def renew(self,uv,uid):
        return self.client.call('renew-evidence',uid=integer(uid),uidvalidity=integer(uv))

    def lookup(self,message):
        require(message.source_uidvalidity>0,'Source UIDVALIDITY required.')
        proof=self.client.call('evidence',uid=message.uid,uidvalidity=message.source_uidvalidity)
        return validate_proof(proof,message,self.host,self.account,self.key_policy_sha256,self.clock,self.namespace_sha256)


class ProofBroker(Broker):
    def dispatch(self,request,uid):
        require(uid==self.client_uid,'Untrusted evidence peer.')
        require(type(request) is dict and set(request)=={'operation','arguments'} and request['operation'] in ('evidence','renew-evidence'), 'Evidence operation prohibited.')
        args=request['arguments']
        require(type(args) is dict and set(args)=={'uid','uidvalidity'},'Only exact source identity accepted.')
        operation=self.organizer.renew if request['operation']=='renew-evidence' else self.organizer.lookup
        return operation(integer(args['uidvalidity']),integer(args['uid']))


