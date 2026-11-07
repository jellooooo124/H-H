"""Disposable real FastAPI server for node contract tests; no provider requests."""
import json
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from app.main import app
import uvicorn

# Seed stored events directly: exercising intake/dispatch is covered by backend
# tests. The node under test must still traverse real HTTP auth and triage routes.
for event_id, symptoms in [('CHK-NODE-001', {}), ('CHK-NODE-URGENT', {'chest_pain': True})]:
    app.state.coordination.create_checkin('DEMO-P001', event_id, {'symptoms': symptoms})
sock = socket.socket()
sock.bind(('127.0.0.1', int(os.environ.get('HAH_TEST_PORT', '0'))))
sock.listen(128)
print(json.dumps({'port': sock.getsockname()[1]}), flush=True)
server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
server.run(sockets=[sock])
