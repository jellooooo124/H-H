"""Database connectivity and tamper-evident chain check infrastructure adapter."""
class SqlHealthReader:
    def __init__(self,store):
        self.store=store

    def check(self):
        self.store.db.execute('SELECT 1')
        return self.store.verify_audit()
