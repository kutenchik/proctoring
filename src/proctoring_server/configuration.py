"""Owned profiles and read-only effective policy; mutations use existing CSRF."""
import json
from uuid import uuid4
from fastapi import Request
from proctoring.exam_policy import catalog, default_policy, validate_policy
from .service import Problem, text_field, encoded, iso


def checked(value):
    try:return validate_policy(value)
    except (ValueError,TypeError) as e:raise Problem('invalid_monitoring_policy',str(e)) from None

def effective(connection, attempt):
    initial=json.loads(attempt['policy_snapshot']).get('monitoring_policy')
    rows=connection.execute("SELECT p.*,c.status,c.result FROM monitoring_policy_changes p JOIN live_commands c ON c.id=p.command_id WHERE p.attempt_id=? ORDER BY p.revision,p.created_at,p.command_id",(attempt['id'],)).fetchall()
    applied=[r for r in rows if r['status']=='applied']
    last=applied[-1] if applied else None
    return {'policy':checked(json.loads(last['new_policy']) if last else initial) if initial else None,'revision':last['revision'] if last else 0,
            'legacy':initial is None,'history':[{'command_id':r['command_id'],'revision':r['revision'],'status':r['status'],
                'teacher_id':r['teacher_id'],'reason':r['reason'],'created_at':iso(r['created_at']),
                'old_policy':json.loads(r['old_policy']),'new_policy':json.loads(r['new_policy'])} for r in rows]}

def install_configuration_routes(app, service, owner):
    prefix='/api/v1'
    def owned(db,teacher,id):
        row=db.execute('SELECT * FROM configuration_profiles WHERE id=? AND teacher_id=?',(id,teacher)).fetchone()
        if row is None:raise Problem('not_found','Configuration profile not found',404)
        return row
    def document(row):
        return {'id':row['id'],'name':row['name'],'policy':checked(json.loads(row['policy'])),
                'version':row['version'],'builtin':False,'updated_at':iso(row['updated_at'])}
    @app.get(prefix+'/configuration/catalog')
    def get_catalog(request:Request):
        owner(request);return catalog()
    @app.get(prefix+'/configuration/profiles')
    def profiles(request:Request):
        teacher=owner(request)
        with service.database.connect() as db:
            return {'items':[{'id':'default','name':'Default','policy':default_policy(),'version':1,'builtin':True}]+[
                document(r) for r in db.execute('SELECT * FROM configuration_profiles WHERE teacher_id=? ORDER BY name,id',(teacher,))]}
    @app.get(prefix+'/configuration/profiles/{id}')
    def get_profile(request:Request,id:str):
        teacher=owner(request)
        if id=='default':return {'id':'default','name':'Default','policy':default_policy(),'version':1,'builtin':True}
        with service.database.connect() as db:return document(owned(db,teacher,id))
    @app.post(prefix+'/configuration/profiles',status_code=201)
    def create(request:Request,data:dict):
        teacher=owner(request,True)
        if set(data)!={'name','policy'}:raise Problem('invalid_profile','Expected name and policy')
        name=text_field(data,'name',120);policy=checked(data['policy']);id=uuid4().hex;now=service.clock()
        with service.database.connect(write=True) as db:
            db.execute('INSERT INTO configuration_profiles VALUES (?,?,?,?,?,?,?)',(id,teacher,name,encoded(policy),1,now,now))
            service.audit(db,teacher,'profile_created',id,now)
            return document(owned(db,teacher,id))
    @app.put(prefix+'/configuration/profiles/{id}')
    def update(request:Request,id:str,data:dict):
        teacher=owner(request,True)
        if set(data)!={'name','policy','version'} or type(data['version']) is not int:raise Problem('invalid_profile','Expected name, policy and version')
        name=text_field(data,'name',120);policy=checked(data['policy'])
        with service.database.connect(write=True) as db:
            row=owned(db,teacher,id)
            if row['version']!=data['version']:raise Problem('profile_conflict','Profile changed; reload before saving',409)
            db.execute('UPDATE configuration_profiles SET name=?,policy=?,version=version+1,updated_at=? WHERE id=?',(name,encoded(policy),service.clock(),id))
            service.audit(db,teacher,'profile_updated',id,service.clock())
            return document(owned(db,teacher,id))
    @app.delete(prefix+'/configuration/profiles/{id}')
    def delete(request:Request,id:str):
        teacher=owner(request,True)
        with service.database.connect(write=True) as db:
            owned(db,teacher,id);db.execute('DELETE FROM configuration_profiles WHERE id=?',(id,))
            service.audit(db,teacher,'profile_deleted',id,service.clock())
        return {'deleted':True}
    @app.get(prefix+'/attempts/{id}/monitoring-policy')
    def attempt_policy(request:Request,id:str):
        teacher=owner(request)
        with service.database.connect() as db:return effective(db,service.owned_attempt(db,teacher,id))
