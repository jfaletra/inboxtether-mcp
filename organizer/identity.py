"""Root-pinned exact wire names and folder identities; never derived from display names."""
from dataclasses import dataclass
import re
import ipaddress
from .model import CATEGORIES,digest,integer,require

NAMES = ('INBOX', *CATEGORIES)

@dataclass(frozen=True)
class MailboxNamespace:
    entries: tuple
    fingerprint: str

    def path(self, name):
        require(name in NAMES, 'Folder outside organizer scope.')
        return dict((k,p) for k,p,u in self.entries)[name]

    def identity(self, name):
        require(name in NAMES, 'Folder outside organizer scope.')
        return dict((k,u) for k,p,u in self.entries)[name]


def validate_namespace(values, host, account):
    require(type(values) is dict and set(values)=={'version','login_account','verifier_login_account','logical_account','host','folders','namespace','attestation','mailboxes','connect_ip'}, 'Exact namespace binding required.')
    require(values['version']==2 and values['namespace']=='exact-mailboxes-v2' and values['host']==host and values['logical_account']==account, 'Namespace scope mismatch.')
    require(type(values['connect_ip']) is str, 'Pinned connection IP required.')
    try: ipaddress.ip_address(values['connect_ip'])
    except ValueError: require(False, 'Pinned connection IP required.')
    principals=[values[k] for k in ('login_account','verifier_login_account','logical_account')]
    require(all(type(p) is str and re.fullmatch(r'[A-Za-z0-9_.+@-]{1,320}',p) for p in principals) and len(set(p.casefold() for p in principals))==3, 'Three distinct ordinary IMAP principals required.')
    require(values['folders']==list(NAMES) and values['attestation']=='owner-reviewed-server-mapping', 'Exact server mapping attestation required.')
    boxes=values['mailboxes'];require(type(boxes) is dict and set(boxes)==set(NAMES), 'Exactly six explicit mailbox identities required.')
    entries=[]
    for name in NAMES:
        box=boxes[name];require(type(box) is dict and set(box)=={'path','uidvalidity'}, 'Exact path/identity required.')
        p=box['path']
        # Deliberately bounded ASCII wire names; no quoting, wildcard, traversal or implicit normalization.
        require(type(p) is str and 0<len(p)<=512 and re.fullmatch(r'[A-Za-z0-9_@.+/-]+',p) and all(s not in ('','.','..') for s in p.split('/')), 'Unsupported literal mailbox path.')
        entries.append((name,p,integer(box['uidvalidity'])))
    require(len({p.casefold() for _,p,_ in entries})==6, 'Duplicate or aliased mailbox mapping.')
    return MailboxNamespace(tuple(entries),digest(values))


def validate_binding(values,config):
    if type(values) is dict and values.get('version')==2:
        ns=validate_namespace(values,config.host,config.account)
        require(config.principal_binding_sha256==ns.fingerprint and all(ns.identity(n)==config.pins[n] for n in CATEGORIES), 'Namespace pin mismatch.')
        return values['login_account']
    # Explicit existing fixed-namespace contract remains supported, with no automatic conversion.
    require(type(values) is dict and set(values)=={'version','login_account','logical_account','host','folders','namespace','attestation'},'Dedicated principal binding required.')
    require(values['version']==1 and values['namespace']=='fixed-inbox-v1' and values['host']==config.host and values['logical_account']==config.account,'Namespace scope mismatch.')
    require(type(values['login_account']) is str and values['login_account']!=config.account and 0<len(values['login_account'])<=320 and not any(ord(c)<32 for c in values['login_account']),'Dedicated login principal required.')
    require(values['folders']==list(NAMES) and values['attestation']=='owner-reviewed-server-mapping','Exact server mapping attestation required.')
    require(config.principal_binding_sha256==digest(values),'Principal mapping pin mismatch.')
    return values['login_account']
