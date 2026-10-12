"""Opaque-identifier-only n8n dispatcher, isolated from the application layer."""
from __future__ import annotations
import httpx

class N8NCaseDispatcher:
    def __init__(self, settings, override=None):
        self.url = settings.webhook_url
        self.override = override

    async def dispatch_case(self, case_id: str) -> None:
        payload = {'case_id': case_id}
        if self.override is not None:
            await self.override(payload)
            return
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.post(self.url, json=payload)
            response.raise_for_status()
