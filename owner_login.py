"""Single-owner password login in the existing review web process. No database/IdP."""
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
import asyncio,hashlib,hmac,json,logging,os,re,secrets,stat,time
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse
from starlette.routing import Route
from approval_web import CSRF,page,visible,private_key
from approval_broker import BrokerClient,ReviewError
from draft_assistant import https_url,ID
from journal import require,digest

AUTH_COOKIE='__Host-inboxtether-owner'
LOGIN_COOKIE='__Host-inboxtether-login'
TTL=900
log=logging.getLogger('inboxtether.review')

def review_diagnostic(code,key=None):
    # Fixed codes and validated batch identifiers only: never exception text,
    # cookies, passwords, principal details, request bodies or message fields.
    safe=key if isinstance(key,str) and ID.fullmatch(key) else '-'
    log.warning('review_request code=%s batch=%s',code,safe)

@dataclass(frozen=True)
class LocalConfig:
    origin:str
    owner_id:str
    owner_file:Path
    broker_socket:Path
    web_socket:Path
    csrf_key:bytes
    auth_mode:str='local_password'
    path_prefix:str=''
    @property
    def principal(self):return {'kind':'local-owner','id':self.owner_id}
    @classmethod
    def load(cls):
        from organizer.runtime import load_protected_json
        v=load_protected_json(os.environ['INBOXTETHER_OWNER_CONFIG'])
        require(set(v)=={'origin','owner_id','owner_file','broker_socket','web_socket','csrf_key_file','path_prefix'},'Exact local-owner configuration required')
        require(type(v['owner_id']) is str and re.fullmatch('[0-9a-f]{32}',v['owner_id']),'Fixed owner ID required')
        paths=[Path(v[k]) for k in ('owner_file','broker_socket','web_socket','csrf_key_file')]
        require(all(p.is_absolute() for p in paths),'Absolute protected paths required')
        require(v['path_prefix']=='/inboxtether','Dedicated approval path required')
        result=cls(https_url(v['origin'],origin=True),v['owner_id'],*paths[:3],private_key(paths[3]),path_prefix=v['path_prefix'])
        credentials(result);return result

def credentials(config):
    p=config.owner_file
    for parent in p.parents:
        s=parent.lstat();require(not parent.is_symlink() and s.st_uid in (0,os.geteuid()) and not s.st_mode&0o022,'Unsafe owner-file ancestry')
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        s=os.fstat(fd);require(stat.S_ISREG(s.st_mode) and s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o600 and s.st_nlink==1 and s.st_size<=8192,'Unsafe owner credential file')
        raw=os.read(fd,8193);require(len(raw)<=8192,'Owner file too large');v=json.loads(raw)
    finally:os.close(fd)
    require(set(v)=={'owner_id','username','password_hash'} and v['owner_id']==config.owner_id,'Owner identity changed')
    require(type(v['username']) is str and re.fullmatch('[A-Za-z0-9_.@+-]{1,80}',v['username']),'Invalid dedicated username')
    require(type(v['password_hash']) is str,'Argon2id hash required')
    m=re.fullmatch(r'\$argon2id\$v=19\$m=(\d+),t=(\d+),p=(\d+)\$[A-Za-z0-9+/]{22,86}\$[A-Za-z0-9+/]{43}',v['password_hash'])
    require(m and 19456<=int(m[1])<=65536 and 2<=int(m[2])<=6 and 1<=int(m[3])<=4,'Unsupported password hash parameters')
    return v,hashlib.sha256(raw).hexdigest()

class LoginState:
    def __init__(self,config,clock=time.time):
        self.config,self.clock=config,clock;self.version=None;self.sessions={};self.challenges={};self.failures=[]
        self.reload()
    def reload(self):
        try:value,version=credentials(self.config)
        except Exception:
            self.sessions.clear();self.challenges.clear();self.version=None;raise
        if version!=self.version:self.sessions.clear();self.challenges.clear();self.version=version
        now=self.clock()
        self.sessions={k:v for k,v in self.sessions.items() if v['expires']>now}
        self.challenges={k:v for k,v in self.challenges.items() if v['expires']>now}
        self.failures=[t for t in self.failures if t>now-60]
        return value
    @staticmethod
    def key(token):
        require(type(token) is str and re.fullmatch('[0-9a-f]{64}',token),'Authentication required')
        return hashlib.sha256(token.encode()).hexdigest()
    def session(self,token):
        self.reload();v=self.sessions.get(self.key(token));require(v is not None,'Authentication required');return v
    def challenge(self,batch):
        self.reload()
        if len(self.challenges)>=32:self.challenges.pop(next(iter(self.challenges)))
        token=secrets.token_hex(32);v={'nonce':secrets.token_hex(32),'batch':batch,'expires':self.clock()+300}
        self.challenges[self.key(token)]=v;return token,v
    @staticmethod
    def verify_password(credential,username,password):
        if type(password) is not str or len(password.encode('utf-8'))>1024:return False
        try:Argon2id.verify_phc_encoded(password.encode('utf-8'),credential['password_hash']);valid=True
        except Exception:valid=False
        return valid and type(username) is str and hmac.compare_digest(username.encode('utf-8'),credential['username'].encode('utf-8'))
    def finish_login(self,valid,version,previous=None):
        self.reload()
        require(version==self.version,'Password changed during login')
        if not valid:self.failures.append(self.clock());return None
        if previous:
            try:self.sessions.pop(self.key(previous),None)
            except Exception:pass
        if len(self.sessions)>=8:self.sessions.pop(next(iter(self.sessions)))
        token=secrets.token_hex(32)
        self.sessions[self.key(token)]={'nonce':secrets.token_hex(32),'expires':self.clock()+TTL,'version':self.version}
        return token

def cookie(request,name):
    found=[]
    for key,value in request.scope['headers']:
        if key==b'cookie':
            for field in value.decode('latin-1').split(';'):
                k,sep,v=field.strip().partition('=')
                if k==name:found.append(v)
    require(len(found)<=1,'Duplicate session cookie');return found[0] if found else None

def redirect(path):
    response=RedirectResponse(path,status_code=303)
    response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer'
    return response

def set_cookie(response,name,value,seconds):response.set_cookie(name,value,max_age=seconds,secure=True,httponly=True,samesite='strict',path='/')

def create_app(config,broker=None,clock=time.time):
    from move_web import render
    broker=broker or BrokerClient(config.broker_socket);state=LoginState(config,clock);csrf=CSRF(config.csrf_key)
    owner=config.principal;password_gate=asyncio.Lock();prefix=config.path_prefix
    require(prefix in ('','/inboxtether'),'Invalid approval path')
    def item(kind,version,expires):return {'draft_id':kind,'fingerprint':digest(version),'expires':expires}
    def host(request):require(request.headers.getlist('host')==[urlsplit(config.origin).netloc],'Wrong review host')
    async def form(request,names):
        require(request.headers.getlist('origin')==[config.origin] and request.headers.get('sec-fetch-site','same-origin')=='same-origin','Same-origin submission required')
        require(request.headers.get('content-type')=='application/x-www-form-urlencoded','Form required')
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk);require(len(body)<=8192,'Form too large')
        values=parse_qs(bytes(body).decode('utf-8'),strict_parsing=True,max_num_fields=len(names),keep_blank_values=True)
        require(set(values)==set(names) and all(len(v)==1 for v in values.values()),'Exact form fields required')
        return {k:v[0] for k,v in values.items()}
    async def login(request):
        try:
            host(request);state.reload()
            if request.method=='GET':
                params=parse_qs(request.url.query,strict_parsing=True,max_num_fields=1)
                require(not params or set(params)=={'batch'} and len(params['batch'])==1,'Invalid return target')
                batch=params.get('batch',[''])[0];require(not batch or ID.fullmatch(batch),'Invalid batch ID')
                token,c=state.challenge(batch);challenge=item('owner-login',batch,c['expires'])
                proof=csrf.issue(owner,c['nonce'],challenge,'login')
                response=page('<h1>InboxTether owner login</h1><p>Sign in to review proposed moves. Signing in moves no messages.</p><form method="post" action="'+prefix+'/login"><label>Username <input name="username" autocomplete="username" required maxlength="80"></label><label>Password <input type="password" name="password" autocomplete="current-password" required maxlength="1024"></label><input type="hidden" name="batch" value="'+visible(batch)+'"><input type="hidden" name="csrf" value="'+proof+'"><button>Sign in</button></form>')
                set_cookie(response,LOGIN_COOKIE,token,300);return response
            require(not request.url.query,'No login query on POST')
            v=await form(request,('username','password','batch','csrf'))
            key=state.key(cookie(request,LOGIN_COOKIE));c=state.challenges.pop(key,None)
            require(c and c['expires']>clock() and c['batch']==v['batch'],'Login form expired')
            csrf.verify(v['csrf'],owner,c['nonce'],item('owner-login',c['batch'],c['expires']),'login')
            if len(state.failures)>=5 or password_gate.locked():
                response=page('<h1>Please wait before trying again</h1>',429);response.headers['Retry-After']='60';return response
            # Hashing is deliberately not on the event loop. No persistent login tokens.
            async with password_gate:
                credential=state.reload();version=state.version
                valid=await run_in_threadpool(state.verify_password,credential,v['username'],v['password'])
                token=state.finish_login(valid,version,cookie(request,AUTH_COOKIE))
            if token is None:return page('<h1>Login failed</h1><p>Username or password was incorrect. Reopen login to try again.</p>',403)
            response=redirect(prefix+'/review/'+c['batch'] if c['batch'] else prefix+'/');set_cookie(response,AUTH_COOKIE,token,TTL);response.delete_cookie(LOGIN_COOKIE,path='/',secure=True,httponly=True,samesite='strict');return response
        except Exception:return page('<h1>Login unavailable</h1><p>Reopen the login page and try again.</p>',403)
    async def review(request):
        key=None;stage='request_validation'
        try:
            host(request);require(not request.url.query,'No query allowed')
            key=request.path_params['draft_id'];require(ID.fullmatch(key),'Invalid batch ID')
            try:session=state.session(cookie(request,AUTH_COOKIE))
            except Exception:
                review_diagnostic('authentication_required',key)
                return redirect(prefix+'/login?batch='+key) if request.method=='GET' else page('<h1>Sign in again</h1>',403)
            stage='broker'
            value=await run_in_threadpool(broker.call,'review',key,owner)
            if value['expires']<=clock() or value['state']=='expired':
                review_diagnostic('expired',key)
                return page('<h1>Review expired</h1><p>This manifest cannot be approved. No messages were moved by opening this page.</p>',410)
            stage='render'
            if request.method=='GET':
                logout_proof=csrf.issue(owner,session['nonce'],item('logout',session['version'],session['expires']),'logout')
                return render(value,owner,None,csrf,session['nonce'],logout_token=logout_proof,logout_action=prefix+'/logout')
            stage='approval_validation'
            fields=await form(request,('decision','csrf'));decision=fields['decision']
            require(value['state']=='pending' and decision in ('approved','rejected'),'Review already decided')
            csrf.verify(fields['csrf'],owner,session['nonce'],value,decision)
            # Recheck after async broker/form processing, before approval crosses IPC.
            require(state.session(cookie(request,AUTH_COOKIE))==session,'Session changed')
            stage='approval_submission'
            await run_in_threadpool(broker.call,'decide',key,owner,fingerprint=value['fingerprint'],decision=decision)
            return page('<h1>'+('Approval recorded' if decision=='approved' else 'Batch rejected')+'</h1><p>No messages moved. Return to your assistant; execution requires this exact unexpired approval.</p>')
        except ReviewError as exc:
            review_diagnostic(exc.code,key)
            if stage=='approval_submission':
                return page('<h1>Approval outcome unconfirmed</h1><p>Do not resubmit. Check this batch status through your assistant. This page does not execute moves.</p>',503)
            messages={'missing_batch':('Review not found',404),'authorization':('Review access denied',403),
                      'expired':('Review expired',410),'broker_timeout':('Review service busy',503),
                      'broker_error':('Review service unavailable',503)}
            title,status=messages[exc.code]
            return page('<h1>'+title+'</h1><p>No approval was submitted. Opening this page moves nothing.</p>',status)
        except Exception:
            review_diagnostic(stage+'_error',key)
            if stage=='approval_submission':
                return page('<h1>Approval outcome unconfirmed</h1><p>Do not resubmit. Check this batch status through your assistant.</p>',503)
            return page('<h1>Review request unavailable</h1><p>No approval was submitted. Open the exact review link; do not submit a move approval from an error page.</p>',409)
    async def home(request):
        try:
            host(request);session=state.session(cookie(request,AUTH_COOKIE))
            token=csrf.issue(owner,session['nonce'],item('logout',session['version'],session['expires']),'logout')
            return page('<h1>InboxTether owner signed in</h1><p>Open the exact review link supplied by your assistant. Login does not approve moves.</p><form method="post" action="'+prefix+'/logout"><input type="hidden" name="csrf" value="'+token+'"><button>Sign out</button></form>')
        except Exception:return redirect(prefix+'/login')
    async def logout(request):
        try:
            host(request);require(not request.url.query,'No query allowed')
            session=state.session(cookie(request,AUTH_COOKIE));v=await form(request,('csrf',))
            csrf.verify(v['csrf'],owner,session['nonce'],item('logout',session['version'],session['expires']),'logout')
            state.sessions.pop(state.key(cookie(request,AUTH_COOKIE)),None)
            response=redirect(prefix+'/login');response.delete_cookie(AUTH_COOKIE,path='/',secure=True,httponly=True,samesite='strict');return response
        except Exception:return page('<h1>Sign out request refused</h1>',403)
    app=Starlette(routes=[Route(prefix+'/',home),Route(prefix+'/login',login,methods=['GET','POST']),Route(prefix+'/logout',logout,methods=['POST']),Route(prefix+'/review/{draft_id}',review,methods=['GET','POST'])])
    app.state.owner_login=state
    return app
