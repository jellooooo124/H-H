"""Disposable PostgreSQL-only cross-connection HMAC and transaction integrity tests."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
import uuid

import pytest

from app.config import Settings
from app.store import Store


def _settings():
    if os.getenv("PG_TEST_ISOLATED") != "YES" or not os.getenv("PG_TEST_URL"):
        pytest.skip("Requires isolated disposable PostgreSQL test database")
    pytest.importorskip("psycopg")
    cfg = replace(Settings.from_env(), database_url=os.environ["PG_TEST_URL"], auth_mode="demo")
    cfg.validate()
    return cfg


def test_separate_connections_serialize_hmac_audit_appends():
    cfg = _settings()
    stores = [Store(cfg) for _ in range(4)]
    case_ids = ["PG-CI-" + uuid.uuid4().hex for _ in stores]
    try:
        def insert(entry):
            store, case_id = entry
            store.create(case_id, "DEMO-P001", {"is_synthetic": True, "source": "concurrent-ci"})
            return case_id
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(insert, zip(stores, case_ids)))
        assert set(results) == set(case_ids)
        assert all(stores[0].get(case_id)["status"] == "RECEIVED" for case_id in case_ids)
        assert stores[1].verify_audit() is True
    finally:
        for store in stores:
            store.db.close()


def test_postgres_rolls_back_case_when_audit_write_fails():
    cfg = _settings()
    store = Store(cfg)
    case_id = "PG-ROLLBACK-" + uuid.uuid4().hex
    real_audit = store.audit
    try:
        def fail_audit(*_args, **_kwargs):
            raise RuntimeError("Injected audit failure")
        store.audit = fail_audit
        with pytest.raises(RuntimeError, match="Injected audit failure"):
            store.create(case_id, "DEMO-P001", {"is_synthetic": True})
        assert store.db.execute("SELECT 1 FROM cases WHERE case_id=?", (case_id,)).fetchone() is None
        store.audit = real_audit
        store.create(case_id, "DEMO-P001", {"is_synthetic": True})
        assert store.verify_audit() is True
    finally:
        store.audit = real_audit
        store.db.close()


def test_postgres_atomic_claim_across_independent_workers():
    """Only one PostgreSQL worker may acquire one due job; all connections are real."""
    from app.operations23 import QueueJob

    cfg = _settings()
    stores = [Store(cfg) for _ in range(8)]
    jobs = [QueueJob(store) for store in stores]
    ref = "CI-ATOMIC-" + uuid.uuid4().hex
    try:
        original_job_id = jobs[0].enqueue("CHECKIN_DISPATCH", ref)
        # This test exercises eight separate psycopg connections, rather than
        # threads sharing a single Store lock.
        with ThreadPoolExecutor(max_workers=8) as pool:
            claimed = list(pool.map(lambda q: q.claim(), jobs))
        winners = [row for row in claimed if row and row["reference_id"] == ref]
        assert len(winners) == 1, winners
        assert winners[0]["job_id"] == original_job_id
        assert winners[0]["attempts"] == 1
        stored = stores[0].db.execute(
            "SELECT status,attempts FROM dispatch_jobs WHERE job_id=?",
            (original_job_id,)
        ).fetchone()
        assert stored["status"] == "LEASED"
        assert stored["attempts"] == 1
        jobs[0].delivered("CHECKIN_DISPATCH", ref)
        assert stores[0].verify_audit() is True
    finally:
        for store in stores:
            store.db.close()


def test_postgres_multiworker_claims_distinct_jobs():
    """Concurrent claims of several jobs cannot duplicate a lease."""
    from app.operations23 import QueueJob

    cfg = _settings()
    stores = [Store(cfg) for _ in range(6)]
    jobs = [QueueJob(s) for s in stores]
    refs = ["CI-BATCH-" + uuid.uuid4().hex for _ in range(4)]
    try:
        expected = {jobs[0].enqueue("CHECKIN_DISPATCH", ref) for ref in refs}
        with ThreadPoolExecutor(max_workers=6) as pool:
            claimed = list(pool.map(lambda q: q.claim(), jobs))
        acquired = [row for row in claimed if row and row["job_id"] in expected]
        assert len(acquired) == len(refs), acquired
        assert {row["job_id"] for row in acquired} == expected
        assert all(row["attempts"] == 1 for row in acquired)
        for ref in refs:
            jobs[0].delivered("CHECKIN_DISPATCH", ref)
        assert stores[0].verify_audit() is True
    finally:
        for store in stores:
            store.db.close()
