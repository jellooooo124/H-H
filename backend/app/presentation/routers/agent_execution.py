"""n8n-facing internal HTTP adapter; no clinical logic is implemented here."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from ...domain.workflow_rules import WorkflowError
from .clinical_cases import translate

class CaseRef(BaseModel):
    case_id:str
class ExecuteTool(CaseRef):
    tool:str

def build_router(service,internal):
    router=APIRouter(tags=['internal agents'])

    @router.post('/internal/start')
    def start(ref:CaseRef,ok=Depends(internal)):
        try:return service.start(ref.case_id)
        except WorkflowError as exc:raise translate(exc) from exc

    @router.post('/internal/plan')
    def plan(ref:CaseRef,ok=Depends(internal)):
        try:return service.plan(ref.case_id)
        except WorkflowError as exc:raise translate(exc) from exc

    @router.post('/internal/tool')
    def tool(data:ExecuteTool,ok=Depends(internal)):
        try:return service.execute_tool(data.case_id,data.tool)
        except WorkflowError as exc:raise translate(exc) from exc

    @router.post('/internal/finalize')
    def finalize(ref:CaseRef,ok=Depends(internal)):
        try:return service.finalize(ref.case_id)
        except WorkflowError as exc:raise translate(exc) from exc

    @router.post('/internal/knowledge/reindex')
    def reindex(ok=Depends(internal)):
        try:return service.reindex()
        except WorkflowError as exc:raise translate(exc) from exc
    return router
