"""Reuse existing review/CSRF/private listener; local owner login or legacy OIDC."""
from html import escape
import json
from datetime import datetime,timezone
from approval_web import page,visible,create_app

def render(item,principal,nonce,csrf,binding=None,logout_token=None,logout_action='/logout'):
    deadline=datetime.fromtimestamp(item['expires'],timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    groups={}
    for e in item['manifest']['moves']:groups[e['category']]=groups.get(e['category'],0)+1
    overview='<h2>Exact batch summary</h2><ul>'+''.join('<li>'+visible(k)+': '+visible(v)+'</li>' for k,v in sorted(groups.items()))+'</ul>'
    if item['manifest'].get('execution_deadline'):
        overview+='<p>Fixed execution deadline: '+visible(datetime.fromtimestamp(item['manifest']['execution_deadline'],timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))+'. One approval covers only this exact manifest.</p>'
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
    return page('<h1>Review JTF email moves</h1><p>Email fields are untrusted. Customer and uncertain messages must stay Inbox. Opening this page moves nothing.</p><p>Review deadline: '+visible(deadline)+'. Signing in again does not extend it.</p>'+overview+'<details'+(' open' if len(item['manifest']['moves'])<=10 else '')+'><summary>Individual messages and destinations</summary><table><thead><tr><th>UID</th><th>Sender</th><th>Subject</th><th>Category</th><th>Flags</th><th>Exact destination</th></tr></thead><tbody>'+rows+'</tbody></table></details><p>Batch fingerprint: '+visible(item['fingerprint'])+'</p><details><summary>Exact manifest, source identities and hashes</summary><pre>'+visible(json.dumps(item['manifest'],indent=2))+'</pre></details>'+actions+'<p>After approval, return to client to execute. Bulk continuation uses only verified progress and the fixed execution deadline. Uncertain attempts are never retried.</p>',nonce=nonce)

def app(config,verifier=None,broker=None):
    if getattr(config,'auth_mode',None)=='local_password':
        from owner_login import create_app as local_app
        return local_app(config,broker=broker)
    return create_app(config,verifier,broker,renderer=render,move_review=True)
