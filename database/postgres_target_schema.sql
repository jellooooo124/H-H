-- Hospital-at-Home Care Coordination 2.4: normalized PostgreSQL schema (DESIGN REFERENCE ONLY)
-- This SQL is NOT used by the current SQLite prototype. No real PHI allowed in the demo.
-- For production: apply migrations, encryption/key separation, RLS policies, backups,
-- audit anchoring, IAM, retention, clinical validation, and security review first.
BEGIN;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS patients (
  patient_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), external_ref text UNIQUE NOT NULL,
  care_team_id uuid, status text NOT NULL DEFAULT 'active', consent_version text,
  consent_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS care_episodes (
  episode_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), patient_id uuid NOT NULL REFERENCES patients,
  started_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz,
  active boolean NOT NULL DEFAULT true, version integer NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS observations (
  observation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_event_id text NOT NULL UNIQUE,
  patient_id uuid NOT NULL REFERENCES patients, episode_id uuid REFERENCES care_episodes,
  code text NOT NULL CHECK(code IN ('weight_kg','glucose_mg_dl','heart_rate_bpm','spo2_pct')),
  observed_at timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT now(),
  value_cipher bytea NOT NULL, unit text NOT NULL, device_ref text,
  quality_status text NOT NULL DEFAULT 'unverified', provenance_json jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS observations_patient_time ON observations(patient_id,observed_at DESC);
-- Added in 2.1: external resource deduplication and local provenance registry.
-- This is target schema only, not connected to the SQLite demo runtime.
CREATE TABLE IF NOT EXISTS fhir_source_registry (
  source_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patients,
  source_system text NOT NULL, resource_type text NOT NULL DEFAULT 'Observation',
  remote_resource_id text NOT NULL, fingerprint_sha256 text NOT NULL,
  local_event_id text NOT NULL UNIQUE, imported_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(patient_id,source_system,resource_type,remote_resource_id)
);
CREATE TABLE IF NOT EXISTS monitoring_plans (
  plan_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),patient_id uuid NOT NULL REFERENCES patients,
  observation_code text NOT NULL, expected_interval_minutes integer,
  review_gap_minutes integer NOT NULL CHECK(review_gap_minutes>=60),
  status text NOT NULL DEFAULT 'active', reviewed_by text NOT NULL, reviewed_at timestamptz NOT NULL,
  version integer NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS patient_checkins (
  checkin_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_event_id text NOT NULL UNIQUE,
  patient_id uuid NOT NULL REFERENCES patients, episode_id uuid REFERENCES care_episodes,
  reported_at timestamptz NOT NULL DEFAULT now(), payload_cipher bytea NOT NULL,
  processing_status text NOT NULL DEFAULT 'pending', processed_at timestamptz
);
CREATE TABLE IF NOT EXISTS clinical_cases (
  case_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), external_case_id text UNIQUE NOT NULL,
  patient_id uuid NOT NULL REFERENCES patients, episode_id uuid REFERENCES care_episodes,
  state text NOT NULL, version bigint NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(), input_snapshot_cipher bytea NOT NULL,
  workflow_state_cipher bytea NOT NULL, model_config_version text
);
CREATE INDEX IF NOT EXISTS clinical_cases_patient_time ON clinical_cases(patient_id,created_at DESC);
CREATE TABLE IF NOT EXISTS agent_runs (
  run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), case_id uuid NOT NULL REFERENCES clinical_cases,
  agent_name text NOT NULL, model_id text NOT NULL, prompt_version text NOT NULL,
  output_schema_version text NOT NULL, policy_version text NOT NULL,
  input_digest text NOT NULL, output_cipher bytea NOT NULL,
  started_at timestamptz NOT NULL, completed_at timestamptz,
  result text NOT NULL, error_code text
);
CREATE TABLE IF NOT EXISTS evidence_refs (
  evidence_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), run_id uuid NOT NULL REFERENCES agent_runs,
  source_id text NOT NULL, source_version text NOT NULL, sha256 text NOT NULL,
  retrieval_score double precision, cited_span text, verified boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS care_tasks (
  task_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), idempotency_key text NOT NULL UNIQUE,
  case_id uuid REFERENCES clinical_cases, patient_id uuid NOT NULL REFERENCES patients,
  task_type text NOT NULL, priority text NOT NULL, state text NOT NULL,
  assigned_staff_id text, due_at timestamptz NOT NULL, ack_at timestamptz,
  completed_at timestamptz, outcome text, disposition_cipher bytea,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  version bigint NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS care_tasks_active_sla ON care_tasks(state,due_at);
CREATE TABLE IF NOT EXISTS task_events (
  event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), task_id uuid NOT NULL REFERENCES care_tasks,
  actor_id text NOT NULL, event_type text NOT NULL, event_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS delivery_outbox (
  outbox_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_key text UNIQUE NOT NULL,
  patient_id uuid NOT NULL REFERENCES patients, case_id uuid REFERENCES clinical_cases,
  approved_by text, channel text, status text NOT NULL DEFAULT 'draft',
  content_cipher bytea NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz, delivered_at timestamptz, acknowledged_at timestamptz
);
CREATE TABLE IF NOT EXISTS audit_events (
  event_id bigserial PRIMARY KEY, aggregate_id text NOT NULL,
  event_type text NOT NULL, actor_id text NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now(),
  metadata_redacted jsonb NOT NULL, prev_hash text NOT NULL, event_hash text NOT NULL
);

-- v2.4 proposed normalized production entities. IMPORTANT: runtime SQL lives
-- in backend/app/engagement24.py; this normalized schema is a migration TARGET,
-- not a SQL script that can replace current runtime tables without mapping.
CREATE TABLE IF NOT EXISTS patient_engagement_preferences_v24 (
  patient_id uuid PRIMARY KEY REFERENCES patients, reminder_opt_in boolean NOT NULL DEFAULT false,
  reminder_hour_utc smallint NOT NULL CHECK(reminder_hour_utc BETWEEN 0 AND 23),
  minimum_gap_hours smallint NOT NULL CHECK(minimum_gap_hours BETWEEN 24 AND 168),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS simulated_in_app_prompts_v24 (
  prompt_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), dedupe_key text UNIQUE NOT NULL,
  patient_id uuid NOT NULL REFERENCES patients, kind text NOT NULL,
  state text NOT NULL CHECK(state IN ('PENDING_SIMULATED','SEEN','CANCELLED')),
  created_at timestamptz NOT NULL DEFAULT now(), seen_at timestamptz
);
CREATE INDEX IF NOT EXISTS simulated_prompts_v24_patient ON simulated_in_app_prompts_v24(patient_id,created_at DESC);
CREATE TABLE IF NOT EXISTS operational_snapshots_v24 (
  snapshot_hour timestamptz PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now(),
  metrics_json jsonb NOT NULL
);

-- SECURITY TODO: add tenant/team-scoped PostgreSQL RLS policies with verified session claims;
-- do not grant direct table access to n8n or browser users. Make audit append-only with
-- independently anchored hashes. Disallow arbitrary updates to audit_events.
COMMIT;
