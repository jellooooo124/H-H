"""Security integration tests with RSA-signed synthetic OIDC tokens.
No external IdP, PostgreSQL container or patient data required.
"""
from dataclasses import replace
from types import SimpleNamespace
import os,time,pytest,jwt,httpx
from cryptography.hazmat.primitives.asymmetric import rsa
from app.main import create_app
from app.config import Settings
from app.postgres_compat import PostgresCompat
from test_system import FakeModel,NORMAL

@pytest.fixture
async def oidc_client(tmp_path):
    settings=replace(Settings.from_env(),database_path=str(tmp_path/'oidc-v22.db'),database_url='')
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    s=replace(settings,auth_mode='oidc',oidc_issuer='https://login.example.test/issuer',
        oidc_audience='hah-health-api',oidc_jwks_url='https://login.example.test/jwks.json',
        admin_key='admin-'+'X'*56)
    async def no_net(_):return True
    app=create_app(s,model=FakeModel(),dispatch=no_net)
    class JWKSStub:
        def get_signing_key_from_jwt(self,token):
            h=jwt.get_unverified_header(token)
            if h.get('kid')!='test-rsa-1':raise jwt.PyJWKClientError('Unknown key')
            return SimpleNamespace(key=key.public_key())
    app.state.verifier.jwks=JWKSStub()
    def header(subject='staff-A',groups=['hah-clinician'],**opts):
        claims={'iss':'https://login.example.test/issuer','aud':'hah-health-api',
                'iat':int(time.time()),'exp':int(time.time())+3600,'sub':subject,
                'groups':groups, **opts}
        encoded=jwt.encode(claims,key,algorithm='RS256',headers={'kid':'test-rsa-1'})
        return {'Authorization':'Bearer '+encoded}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        yield c,s,header

@pytest.mark.asyncio
async def test_oidc_unassigned_clinician_sees_no_records(oidc_client):
    c,s,h=oidc_client
    p=h('patient-A',['hah-patient'],patient_ref='DEMO-P001')
    assert (await c.post('/v1/intake',json=NORMAL,headers=p)).status_code==202
    assert (await c.get('/v1/cases',headers=h())).json()==[]
    assert (await c.get('/v2/tasks',headers=h())).json()['tasks']==[]
    assert (await c.get('/v1/cases/HHC-CASE-0001',headers=h())).status_code==403
    assert (await c.get('/v1/audit/HHC-CASE-0001',headers=h())).status_code==403
    assert (await c.get('/v2/patients/DEMO-P001/trends',headers=h())).status_code==403
    assert (await c.get('/v3/fhir/Observation?patient_ref=DEMO-P001',headers=h())).status_code==403
    assert (await c.get('/v2/metrics',headers=h())).status_code==403
    assert (await c.get('/v1/cases/HHC-CASE-0001',headers=p)).status_code==403

@pytest.mark.asyncio
async def test_admin_assignment_and_revoke(oidc_client):
    c,s,h=oidc_client
    p=h('patient-A',['hah-patient'],patient_ref='DEMO-P001')
    assert (await c.post('/v1/intake',json=NORMAL,headers=p)).status_code==202
    body={'clinician_sub':'staff-A','patient_ref':'DEMO-P001','active':True}
    assert (await c.post('/admin/assignments',json=body,headers={'X-Internal-Key':s.internal_key})).status_code==403
    assert (await c.post('/admin/assignments',json=body,headers={'X-Admin-Key':s.admin_key})).status_code==200
    assert len((await c.get('/v1/cases',headers=h())).json())==1
    assert (await c.get('/v1/cases/HHC-CASE-0001',headers=h())).status_code==200
    assert (await c.get('/v1/cases/HHC-CASE-0001',headers=h('staff-B'))).status_code==403
    body['active']=False
    assert (await c.post('/admin/assignments',json=body,headers={'X-Admin-Key':s.admin_key})).status_code==200
    assert (await c.get('/v1/cases',headers=h())).json()==[]
    assert (await c.get('/v1/cases/HHC-CASE-0001',headers=h())).status_code==403

@pytest.mark.asyncio
async def test_oidc_rejects_forged_role_wrong_audience_and_issuer(oidc_client):
    c,s,h=oidc_client
    assert (await c.get('/v1/cases',headers=h(groups=[],role='clinician'))).status_code==403
    assert (await c.get('/v1/cases',headers=h(groups=['hah-clinician','hah-patient']))).status_code==403
    assert (await c.get('/v1/cases',headers=h(groups=['hah-patient']))).status_code==403
    assert (await c.get('/v1/cases',headers=h(aud='other-api'))).status_code==401
    assert (await c.get('/v1/cases',headers=h(iss='https://other.example.test'))).status_code==401
    forged=jwt.encode({'iss':s.oidc_issuer,'aud':s.oidc_audience,'iat':int(time.time()),
                       'exp':int(time.time())+60,'sub':'staff-A','groups':['hah-clinician']},
                      s.jwt_secret,algorithm='HS256',headers={'kid':'test-rsa-1'})
    assert (await c.get('/v1/cases',headers={'Authorization':'Bearer '+forged})).status_code==401
    assert (await c.get('/v1/cases',headers=h(groups=['hah-patient'],patient_ref='REAL-123'))).status_code==403


def test_postgres_sql_adapter_compiles_supported_queries():
    from app.postgres_compat import PostgresCompat
    assert PostgresCompat.convert('BEGIN IMMEDIATE')=='BEGIN'
    assert 'WHERE id=%s' in PostgresCompat.convert('SELECT * FROM cases WHERE id=?')
    assert "status='TRIAGED'" in PostgresCompat.convert('SELECT * FROM checkins WHERE status="TRIAGED"')
    fake=PostgresCompat.__new__(PostgresCompat)
    class Conn:
        def __init__(self):self.calls=[]
        def execute(self,sql,params=()):
            self.calls.append((sql,params));return SimpleNamespace(rowcount=1)
    fake.conn=Conn();fake.in_transaction=False
    fake.execute('INSERT OR IGNORE INTO care_tasks(task_id) VALUES(?)',('TASK-1',))
    assert fake.conn.calls[-1][0]=='INSERT INTO care_tasks(task_id) VALUES(%s) ON CONFLICT DO NOTHING'
    fake.execute('BEGIN IMMEDIATE');assert fake.in_transaction is True
    fake.execute('ROLLBACK');assert fake.in_transaction is False
    fake.executescript('CREATE TABLE things(id INTEGER PRIMARY KEY AUTOINCREMENT, happened_at REAL);')
    assert 'GENERATED BY DEFAULT AS IDENTITY' in fake.conn.calls[-1][0]
    assert 'DOUBLE PRECISION' in fake.conn.calls[-1][0]

@pytest.mark.asyncio
async def test_ops_readiness_does_not_claim_sqlite_is_postgres(tmp_path):
    from app.config import Settings
    s=replace(Settings.from_env(),database_url='',database_path=str(tmp_path/'sqlite_health.db'))
    app=create_app(s,model=FakeModel())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        assert (await c.post('/internal/ops/audit-health',headers={'X-Internal-Key':s.internal_key})).status_code==503
        assert (await c.post('/internal/ops/audit-health')).status_code==401
        assert (await c.get('/health')).json()['db_backend']=='sqlite'

@pytest.mark.asyncio
async def test_case_creation_and_audit_are_atomic_if_audit_fails(tmp_path):
    from app.store import Store
    s=replace(Settings.from_env(),database_url='',database_path=str(tmp_path/'atomic.db'))
    store=Store(s)
    original=store.audit
    def failed_audit(*args,**kwargs):raise RuntimeError('Audit dependency failed')
    store.audit=failed_audit
    with pytest.raises(RuntimeError,match='Audit dependency failed'):
        store.create('HHC-ATOMIC-0001','DEMO-P001',dict(NORMAL))
    assert store.db.execute('SELECT 1 FROM cases WHERE case_id=?',('HHC-ATOMIC-0001',)).fetchone() is None
    store.audit=original
    store.create('HHC-ATOMIC-0001','DEMO-P001',dict(NORMAL))
    assert store.verify_audit() is True

@pytest.mark.asyncio
async def test_hmac_chain_corruption_detected(tmp_path):
    from app.store import Store
    s=replace(Settings.from_env(),database_url='',database_path=str(tmp_path/'chain.db'))
    store=Store(s)
    store.audit('SYSTEM','TEST_EVENT','synthetic',{'synthetic':True})
    assert store.verify_audit()
    store.db.execute("UPDATE audit SET event='TAMPERED' WHERE seq=1")
    assert not store.verify_audit()
