"""Repository boundaries and a few black-box regression invariants, synthetic only."""
import ast
from pathlib import Path
from app.legacy_api import create_app

ROOT=Path(__file__).resolve().parents[1]/'backend'/'app'
SERVICES=['coordination.py','operations23.py','engagement24.py','fhir_bridge.py',
          'communications/service.py','communications/repository.py']


def test_service_modules_do_not_embed_sql():
    for name in SERVICES:
        source=(ROOT/name).read_text()
        tree=ast.parse(source)
        assert '.db.' not in source, f'{name}: direct DB access in service'
        # Portable executable SQL belongs in infrastructure/persistence, not these services.
        assert not any(token in source for token in ['SELECT ', 'INSERT INTO ', 'UPDATE care_tasks ', 'CREATE TABLE ']),name
        assert tree


def test_canonical_sql_repositories_exist():
    expected=['coordination_repository','dispatch_repository','handoff_repository',
              'engagement_repository','fhir_repository','communications_repository']
    for name in expected:
        module=ROOT/'infrastructure'/'persistence'/f'{name}.py'
        assert module.exists()
        assert 'class ' in module.read_text()


def test_composition_root_injects_all_sql_repositories():
    root=(ROOT/'legacy_api.py').read_text()
    for constructor in ['Coordinator(store,repository=','FHIRBridge(store,coordination,repository=',
                        'ShiftHandoff(store,coordination,repository=', 'QueueJob(store,repository=',
                        'Engagement(store,coordination,repository=',
                        'CommunicationService(store,coordination,repository=']:
        assert constructor in root


def test_communication_old_repo_import_remains_alias():
    from app.communications.repository import CommunicationsRepository as old
    from app.infrastructure.persistence.communications_repository import CommunicationsRepository as new
    assert old is new


def test_fhir_repo_methods_not_present_in_bridge_service():
    source=(ROOT/'fhir_bridge.py').read_text()
    assert 'BEGIN IMMEDIATE' not in source
    assert 'with self.s.transaction():' in source
    assert 'self.repo.record_import(' in source


def test_coordination_no_direct_sql_and_policy_preserved():
    source=(ROOT/'coordination.py').read_text()
    assert "URGENT_SYMPTOMS" in source
    assert 'self.repo.insert_observation(' in source
    assert 'self.repo.create_task(' in source
    assert 'self.repo.newly_overdue(' in source


def test_queue_retry_policy_remains_application_owned():
    source=(ROOT/'operations23.py').read_text()
    assert 'MAX_ATTEMPTS=4' in source
    assert 'delay=min(240,60*' in source
    assert 'self.repo.reschedule(' in source
