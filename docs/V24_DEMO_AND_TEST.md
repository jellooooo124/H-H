# V2.4 Demo & Evaluation: Synthetic Patient Engagement

## Key workflow demo paths

**Normal:** Create clinician-approved monitoring plan -> patient opts in -> background watch generates one in-app checkin prompt when gap ≥ min_gap_hours -> patient marks seen -> API returns `delivered_to_patient=false` -> patient submits synthetic Check-in -> monitoring history updates.

**Negative cases:**

- No monitoring plan or opt-out: scheduler creates zero prompts.
- Recent Check-in within gap: creates zero prompts.
- Twice on one UTC date: first at most one, second zero (unique dedupe key).
- Patient role calling clinician alert/evaluation endpoint: HTTP 403.
- Unknown prompt / another patient's prompt: 404 (no cross-patient metadata disclosure).
- Two distinct urgent tasks: two distinct visible groups, zero underlying deletion.
- Two nonurgent tasks with same patient/kind/reason: one visual group containing **both task IDs**.
- Patient changes reminder_opt_in to false: existing pending prompt state becomes CANCELLED, no new prompts.
- API internal endpoint without X-Internal-Key: HTTP 401.
- Model API down: inherited 2.3 fail-closed case processing remains unchanged.

## Measurement definitions

| Metric | Numerator / interpretation | Missing from prototype |
|---|---|---|
| Task acknowledgement latency | Median minutes from `care_tasks.created_at` to `acknowledged_at` for a specified patient/window | Clinical outcome, risk-adjustment |
| Task completion | Count of completed tasks created in specified 7/14/30-day window | Independent audit of actual care |
| Active alert display group count | Number of read-only groups compared to individual active tasks | Real alert reduction (underlying tasks never dropped) |
| Prompt dedup | Simulated prompt IDs per patient per UTC date | SMS delivery and engagement effectiveness |
| Snapshot count | Aggregate per-hour task buckets, opted-in count, prompt count | Protected subgroup performance and patient-days denominator |

**Don't claim sensitivity, false positive rate, reduction in clinician workload, clinical effectiveness or validated personal thresholds from this dataset.**

## Test commands

```bash
pytest -q
python scripts/verify_artifact.py
cd frontend && npm install && npm run build
```

PostgreSQL live opt-in, true Docker/n8n connectivity and Vue production bundle must be run in the user's environment. Manual clinical-action tests must use **synthetic** data only.
