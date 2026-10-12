"""Patient engagement use cases; callers supply an authorized patient reference."""
from __future__ import annotations

class EngagementUseCases:
    WINDOWS=(7,14,30)
    def __init__(self, engagement):
        self.engine=engagement

    def dashboard(self, patient_ref, days):
        self._check_days(days)
        return self.engine.dashboard(patient_ref,days)

    def preferences(self,patient_ref):
        return self.engine.preferences(patient_ref)

    def set_preferences(self,patient_ref,opt_in,hour,gap):
        return self.engine.set_preferences(patient_ref,opt_in,hour,gap)

    def prompts(self,patient_ref):
        return {'prompts':self.engine.prompts(patient_ref),'real_notifications_sent':False}

    def mark_seen(self,patient_ref,prompt_id):
        return self.engine.mark_seen(patient_ref,prompt_id)

    def alert_groups(self,patient_refs):
        return self.engine.alert_groups(patient_refs)

    def evaluation(self,patient_ref,days):
        self._check_days(days)
        return self.engine.evaluation(patient_ref,days)

    def reminder_watch(self):
        return self.engine.reminder_watch()

    def snapshot(self):
        return self.engine.snapshot()

    @classmethod
    def _check_days(cls,days):
        if days not in cls.WINDOWS: raise ValueError('Only 7,14,30 days allowed')
