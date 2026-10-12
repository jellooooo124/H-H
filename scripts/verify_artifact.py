"""Static quality gate for the synthetic n8n release artifact."""
import json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
paths=sorted((ROOT/'workflows').glob('*.json'))
errors=[]
if len(paths)!=15:errors.append('Expected 15 workflow JSONs')
seen_paths=set()
seen_webhook_ids=set()
for path in paths:
    try: w=json.loads(path.read_text())
    except Exception as e:errors.append(f'{path.name}: invalid JSON {e}');continue
    if w.get('active') is not False:errors.append(f'{path.name}: workflow should be inactive on import')
    node_names={n['name'] for n in w['nodes']}
    if len(node_names)!=len(w['nodes']):errors.append(f'{path.name}: duplicate node names')
    for n in w['nodes']:
        if not n['type'].startswith('n8n-nodes-base.'):errors.append(f'{path.name}: unexpected custom node')
        if n['type']=='n8n-nodes-base.httpRequest':
            if not n['parameters']['url'].startswith('http://api:8000/internal/'):
                errors.append(f'{path.name}: unapproved HTTP endpoint in node {n["name"]}')
            headers=n['parameters'].get('headerParameters',{}).get('parameters',[])
            if not any(h['name']=='X-Internal-Key' for h in headers):
                errors.append(f'{path.name}: internal API key absent')
        if n['type']=='n8n-nodes-base.webhook':
            webhook_path=n['parameters']['path']
            if webhook_path in seen_paths:errors.append('Duplicate webhook path '+webhook_path)
            seen_paths.add(webhook_path)
            webhook_id=n.get('webhookId')
            try: parsed=str(uuid.UUID(webhook_id))
            except (ValueError, TypeError, AttributeError):
                errors.append(f'{path.name}: missing or malformed stable webhookId')
                continue
            if webhook_id != parsed:errors.append(f'{path.name}: non-canonical webhookId')
            if webhook_id in seen_webhook_ids:errors.append(f'{path.name}: duplicate webhookId')
            seen_webhook_ids.add(webhook_id)
    for src,conns in w['connections'].items():
        if src not in node_names:errors.append(f'{path.name}: invalid source node {src}')
        for arr in conns.get('main',[]):
            for link in arr:
                if link['node'] not in node_names:errors.append(f'{path.name}: dangling graph edge')
    text=path.read_text()
    for forbidden in ('OPENAI_API_KEY','sk-proj-','sk-test-','Authorization: Bearer'):
        if forbidden in text:errors.append(f'{path.name}: contains secret-like value {forbidden}')
print('n8n workflows:',len(paths),'IDs-only boundary: validated')
if errors:
    for err in errors:print('FAIL:',err)
    sys.exit(1)
print('PASS: well-formed graph, internal-only HTTP nodes, no embedded provider key literals')
