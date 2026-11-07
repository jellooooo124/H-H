"""Security boundaries for the existing endpoints used by the custom node."""
import pytest
from test_system import client, settings, internal_header, patient_header


@pytest.mark.parametrize('path', ['/internal/ops/dispatch-health', '/internal/checkin/triage'])
async def test_custom_node_requires_internal_key(client, settings, path):
    for headers in ({}, {'X-Internal-Key': 'invalid'}, patient_header(settings)):
        result = await client.post(path, json={'event_id': 'CHK-NODE-001'}, headers=headers)
        assert result.status_code == 401
        assert settings.internal_key not in result.text


async def test_custom_node_replay_does_not_duplicate_urgent_task(client, settings):
    coord = client._transport.app.state.coordination
    coord.create_checkin('DEMO-P001', 'CHK-NODE-URGENT', {'symptoms': {'chest_pain': True}})
    for _ in range(2):
        result = await client.post('/internal/checkin/triage', json={'event_id': 'CHK-NODE-URGENT'}, headers=internal_header(settings))
        assert result.status_code == 200
        assert 'chest_pain' not in result.text and 'patient_ref' not in result.text
    assert result.json()['idempotent'] is True
    tasks = coord.tasks(patient_refs=['DEMO-P001'])
    assert len(tasks) == 1 and tasks[0]['priority'] == 'urgent'
    assert client._transport.app.state.store.verify_audit()


async def test_custom_node_health_does_not_dispatch_or_mutate_queue(client, settings):
    queue = client._transport.app.state.dispatch_queue
    queue.enqueue('CHECKIN_DISPATCH', 'CHK-NODE-QUEUED')
    before = queue.counts()
    result = await client.post('/internal/ops/dispatch-health', headers=internal_header(settings))
    assert result.status_code == 200
    assert result.json()['counts'] == before == queue.counts()
    assert result.json()['webhook_ack_is_not_completion'] is True
