"""Linux Docker: load package, import encrypted credential, execute both examples.
Uses disposable data only; never prints credential files or raw execution data.
"""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from cryptography.fernet import Fernet

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[1]
IMAGE = 'docker.n8n.io/n8nio/n8n:2.42.6'


def main():
    with tempfile.TemporaryDirectory(prefix='hah-runtime-') as temp:
        tmp = Path(temp)
        env = dict(os.environ, APP_INTERNAL_KEY=secrets.token_hex(32),
                   APP_TOKEN_SECRET=secrets.token_hex(32), APP_ENCRYPTION_KEY=Fernet.generate_key().decode(),
                   N8N_ENCRYPTION_KEY=secrets.token_hex(32), DB_PATH=str(tmp / 'api.db'),
                   DATABASE_URL='', AUTH_MODE='demo', DEMO_MODE='true', OPENAI_API_KEY='',
                   KNOWLEDGE_DIR=str(ROOT / 'knowledge'))
        state = tmp / 'state'
        install = state / '.n8n/nodes/node_modules/n8n-nodes-hah'
        install.mkdir(parents=True)
        shutil.copytree(PACKAGE / 'dist', install / 'dist')
        shutil.copy(PACKAGE / 'package.json', install / 'package.json')
        (state / '.n8n/nodes/package.json').write_text(json.dumps({
            'name': 'installed-nodes', 'private': True, 'dependencies': {'n8n-nodes-hah': '0.1.0'}}))
        fixtures = tmp / 'fixtures'
        fixtures.mkdir()
        api = subprocess.Popen([sys.executable, str(PACKAGE / 'tests/serve_api.py')], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            port = json.loads(api.stdout.readline())['port']
            base = f'http://127.0.0.1:{port}'
            for attempt in range(50):
                try:
                    with urllib.request.urlopen(base + '/health', timeout=1): break
                except OSError:
                    time.sleep(.1)
            else: raise RuntimeError('Disposable FastAPI did not start')
            credential = [{'id': 'hahSmokeCredential', 'name': 'Ephemeral H@H', 'type': 'hahApi',
                           'data': {'baseUrl': base, 'apiKey': env['APP_INTERNAL_KEY'], 'allowLocalHttp': True}}]
            (fixtures / 'credential.json').write_text(json.dumps(credential))
            workflows = []
            for file, wid in [('dispatch-health.json', 'hahSmokeHealth'), ('triage-checkin.json', 'hahSmokeTriage')]:
                workflow = json.loads((PACKAGE / 'examples' / file).read_text())
                workflow['id'] = wid
                for node in workflow['nodes']:
                    if node['type'] == 'n8n-nodes-hah.hah':
                        node['credentials'] = {'hahApi': {'id': 'hahSmokeCredential', 'name': 'Ephemeral H@H'}}
                workflows.append(workflow)
            (fixtures / 'workflows.json').write_text(json.dumps(workflows))
            command = ['docker', 'run', '--rm', '--network', 'host', '--security-opt', 'no-new-privileges:true',
                       '--user', f'{os.getuid()}:{os.getgid()}', '-e', 'N8N_USER_FOLDER=/state',
                       '-e', 'N8N_ENCRYPTION_KEY', '-e', 'N8N_DIAGNOSTICS_ENABLED=false',
                       '-e', 'N8N_PERSONALIZATION_ENABLED=false', '-e', 'N8N_VERSION_NOTIFICATIONS_ENABLED=false',
                       '-e', 'N8N_COMMUNITY_PACKAGES_ENABLED=true', '-e', 'N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true',
                       '-v', f'{state}:/state', '-v', f'{fixtures}:/fixtures:ro', IMAGE]

            def run(*args):
                result = subprocess.run(command + list(args), env=env, capture_output=True, text=True, timeout=180)
                output = result.stdout + result.stderr
                if result.returncode:
                    # Only generated test values can occur here; redact all of them.
                    for key in ('APP_INTERNAL_KEY', 'APP_TOKEN_SECRET', 'APP_ENCRYPTION_KEY', 'N8N_ENCRYPTION_KEY'):
                        output = output.replace(env[key], '[redacted]')
                    raise RuntimeError(f'n8n command {args[0]} failed:\n{output[-6000:]}')
                return output

            run('import:credentials', '--input=/fixtures/credential.json')
            run('import:workflow', '--input=/fixtures/workflows.json')
            for wid, node_name in [('hahSmokeHealth', 'Dispatch Health'), ('hahSmokeTriage', 'Triage Check-in'), ('hahSmokeTriage', 'Triage Check-in')]:
                raw = run('execute', '--id=' + wid, '--rawOutput')
                # Startup logs may precede the JSON document. Require an actual
                # successful execution record and target-node output, not exit 0.
                execution = None
                for index, char in enumerate(raw):
                    if char != '{': continue
                    try:
                        value, _ = json.JSONDecoder().raw_decode(raw[index:])
                        if isinstance(value, dict) and 'data' in value and 'resultData' in value['data']:
                            execution = value
                            break
                    except (ValueError, TypeError): pass
                if execution is None: raise RuntimeError('n8n returned no execution record')
                result = execution['data']['resultData']
                if result.get('error'): raise RuntimeError('n8n execution failed; inspect sanitized node error in CI')
                item = result['runData'][node_name][-1]['data']['main'][0][0]['json']
                if node_name == 'Dispatch Health': assert item['healthy'] is True
                else: assert item['event_id'] == 'CHK-NODE-001' and item['status'] == 'TRIAGED'
            assert item['idempotent'] is True
            print('PASS: real n8n package loading, encrypted credential resolution, both example executions and replay')
        finally:
            api.terminate()
            try: api.wait(timeout=5)
            except subprocess.TimeoutExpired:
                api.kill()
                api.wait()


if __name__ == '__main__':
    main()
