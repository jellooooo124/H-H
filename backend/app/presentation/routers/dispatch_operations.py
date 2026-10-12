"""Operations endpoints provide redacted results and require internal authentication."""
from fastapi import APIRouter,Depends
from pydantic import BaseModel
from ...domain.workflow_rules import WorkflowError
from .clinical_cases import translate

class ErrorNotice(BaseModel):
    workflow_name:str='n8n'
    error_code:str='EXECUTION_FAILED'

def build_router(service,case_service,internal):
    router=APIRouter(tags=['internal operations'])

    @router.post('/internal/watchdog')
    def watchdog(ok=Depends(internal)):
        return case_service.watchdog()

    @router.post('/internal/error')
    def error(notice:ErrorNotice,ok=Depends(internal)):
        return service.error(notice.error_code)

    @router.post('/internal/retry-pending')
    async def retry_pending(ok=Depends(internal)):
        return await service.retry_pending()

    @router.post('/internal/ops/audit-health')
    def audit_health(ok=Depends(internal)):
        try:return service.audit_health()
        except WorkflowError as exc:raise translate(exc) from exc

    @router.post('/internal/ops/dispatch-health')
    def dispatch_health(ok=Depends(internal)):
        try:return service.dispatch_health()
        except WorkflowError as exc:raise translate(exc) from exc

    @router.post('/internal/ops/handoff-watch')
    def handoff_watch(ok=Depends(internal)):
        return service.handoff_watch()

    @router.post('/internal/ops/dispatch-drain')
    async def dispatch_drain(ok=Depends(internal)):
        return await service.drain()

    return router
