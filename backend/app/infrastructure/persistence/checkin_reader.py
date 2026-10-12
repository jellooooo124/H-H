"""Synthetic check-in state query adapter; isolate raw SQL from application orchestration."""

class SqlCheckinReader:
    def __init__(self, store):
        self.store=store

    def checkin_status(self,event_id:str):
        with self.store._lock:
            result=self.store.db.execute('SELECT status FROM checkins WHERE event_id=?',(event_id,)).fetchone()
        return result['status'] if result else None
