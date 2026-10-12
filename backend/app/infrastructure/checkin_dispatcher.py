"""Outbound ID-only webhook adapter; medical payloads never leave through n8n."""
from __future__ import annotations
import httpx

class N8NCheckinDispatcher:
    def __init__(self,settings,override=None):
        self.settings=settings
        self.override=override

    async def dispatch_checkin(self,event_id:str) -> None:
        payload={'event_id':event_id}
        if self.override is not None:
            await self.override(payload)
            return
        url=self.settings.webhook_url.replace('hah-case-intake','hah-checkin-intake')
        async with httpx.AsyncClient(timeout=6.0) as client:
            response=await client.post(url,json=payload)
            response.raise_for_status()
