"""Optional live PostgreSQL smoke test, only on an explicit disposable test DB."""
import os,uuid,json,pytest
from dataclasses import replace
from datetime import datetime,timezone
from app.config import Settings
from app.store import Store
from app.coordination import Coordinator
from app.fhir_bridge import FHIRBridge

def test_live_postgres_transactions_and_encryption():
    if os.getenv('PG_TEST_ISOLATED')!='YES' or not os.getenv('PG_TEST_URL'):
        pytest.skip('Set PG_TEST_ISOLATED=YES and PG_TEST_URL to an EMPTY disposable PostgreSQL database')
    pytest.importorskip('psycopg')
    cfg=replace(Settings.from_env(),database_url=os.environ['PG_TEST_URL'],auth_mode='demo')
    s=Store(cfg);assert s.backend=='postgres'
    co=Coordinator(s);f=FHIRBridge(s,co)
    patient='DEMO-P001';rid='pg-'+uuid.uuid4().hex[:10]
    stamp=datetime.now(timezone.utc).isoformat()
    resource={'resourceType':'Observation','id':rid,'status':'final',
        'subject':{'reference':'Patient/'+patient},
        'code':{'coding':[{'system':'http://loinc.org','code':'29463-7'}]},
        'effectiveDateTime':stamp,
        'valueQuantity':{'value':71.3,'system':'http://unitsofmeasure.org','code':'kg'}}
    bundle={'resourceType':'Bundle','type':'collection','entry':[{'resource':resource}]}
    assert f.import_bundle(patient,bundle)['imported']==1
    assert f.import_bundle(patient,bundle)['unchanged']==1
    assert s.verify_audit() is True
    assert s.db.execute('SELECT COUNT(*) n FROM observations').fetchone()['n']>=1
    s.db.close()
