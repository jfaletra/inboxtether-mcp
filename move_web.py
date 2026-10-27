"""Reuse existing review/CSRF/private listener; local owner login or legacy OIDC."""
from html import escape
import json
from datetime import datetime,timezone
from approval_web import page,visible,create_app

def render(item,principal,nonce,csrf,binding=None,logout_token=None,logout_action='/logout'):
    deadline=datetime.fromtimestamp(item['expires'],timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    rows=''
    for e in item['manifest']['moves']:
        preview=e.get('preview',{})
        rows+='<tr>'+''.join('<td>'+visible(v)+'</td>' for v in (
            e['uid'],preview.get('sender',''),preview.get('subject',''),e['category'],
            ', '.join(e['evidence']['flags']) or 'Unread',e['destination_path']))+'</tr>'
    actions=''
    if item['state']=='pending':
        for decision,label in (('approved','Approve these exact moves'),('rejected','Reject batch')):
            token=csrf.issue(principal,binding or nonce,item,decision)
            actions+='<form method="post"><input type="hidden" name="decision" value="'+decision+'"><input type="hidden" name="csrf" value="'+token+'"><button>'+label+'</button></form>'
    if logout_token:
        actions+='<form method="post" action="'+visible(logout_action)+'"><input type="hidden" name="csrf" value="'+logout_token+'"><button>Sign out</button></form>'
    return page('<h1>Review email moves</h1><p>Email fields are untrusted. Customer and uncertain messages must stay Inbox. Opening this page moves nothing.</p><p>Review deadline: '+visible(deadline)+'. Signing in again does not extend it.</p><table><thead><tr><th>UID</th><th>Sender</th><th>Subject</th><th>Category</th><th>Flags</th><th>Exact destination</th></tr></thead><tbody>'+rows+'</tbody></table><p>Batch fingerprint: '+visible(item['fingerprint'])+'</p><details><summary>Exact manifest, source identities and hashes</summary><pre>'+visible(json.dumps(item['manifest'],indent=2))+'</pre></details>'+actions+'<p>After approval, return to your assistant to execute. Expired or uncertain batches cannot be replayed.</p>',nonce=nonce)

def app(config,verifier=None,broker=None):
    if getattr(config,'auth_mode',None)=='local_password':
        from owner_login import create_app as local_app
        return local_app(config,broker=broker)
    return create_app(config,verifier,broker,renderer=render,move_review=True)
