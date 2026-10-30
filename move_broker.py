"""Existing approval broker extended with a peer-restricted Reader capability."""
import os
from approval_broker import Broker, ReviewError
from journal import require
from organization_errors import OrganizationError,translate

class MoveBroker(Broker):
    def __init__(self,service_context,web_uid,reader_uid,owner):
        require(len({web_uid,reader_uid,os.geteuid()})==3,'Distinct executor, Reader and web identities required')
        self.service_context,self.web_uid,self.reader_uid,self.owner=service_context,web_uid,reader_uid,owner
        self.allowed_uids=(web_uid,reader_uid)
    def dispatch(self,request,uid):
        require(type(request) is dict,'Request object required')
        if request.get('operation')=='organize':
            require(uid==self.reader_uid and set(request)=={'operation','action','payload'},'Reader peer required; no owner authority')
            stage='context'
            try:
                selection_write=request['action']=='candidates' and type(request['payload']) is dict and bool({'select_count','exclude_uids'} & set(request['payload']))
                context=self.service_context(read_only=True) if request['action']=='candidates' and not selection_write else self.service_context()
                with context as service:
                    stage={'prepare':'preparation','candidates':'pagination','execute':'execution','consent':'consent'}.get(request['action'],'request')
                    return service.dispatch(request['action'],request['payload'])
            except Exception as exc:
                raise translate(exc,stage) from None
        if request.get('operation')=='review' and (uid!=self.web_uid or request.get('principal')!=self.owner):
            raise ReviewError('authorization')
        require(uid==self.web_uid and request.get('principal')==self.owner,'Owner web peer required')
        require(set(request)<={'operation','draft_id','principal','fingerprint','decision'},'Unexpected owner fields')
        with self.service_context() as service:
            if request['operation']=='review':
                if service.registry.batch(request['draft_id']).read() is None and not getattr(service,'has_correction',lambda key:False)(request['draft_id']):
                    raise ReviewError('missing_batch')
                item=service.status(request['draft_id'])
                return {'draft_id':item['batch_id'],'manifest':item['manifest'],'fingerprint':item['fingerprint'],
                    'state':('expired' if item['expired'] else 'pending') if item['state']=='prepared' else item['state'],
                    'expires':item['manifest']['expires']}
            require(request['operation']=='decide','Unsupported web operation')
            return service.decide(request['draft_id'],request['fingerprint'],request['decision'],request['principal'])

def main():
    from move_runtime import load
    config,context=load()
    with MoveBroker(context,config['web_uid'],config['reader_uid'],config['owner']).server(__import__('pathlib').Path(config['socket'])) as server:
        try:server.serve_forever()
        finally:__import__('pathlib').Path(config['socket']).unlink(missing_ok=True)

if __name__=='__main__':main()
