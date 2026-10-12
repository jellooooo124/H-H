"""Backward-compatible ASGI composition root.

All existing HTTP method/path contracts are registered in presentation routers.
The module path is retained so previous integrations and test imports do not break.
Domain/application layers do not import FastAPI, HTTP clients, or n8n nodes.
"""
import logging
from fastapi import FastAPI
from .config import Settings
from .store import Store
from .rag import Rag
from .agents import LLMClient
from .policy import assess
from .coordination import Coordinator
from .fhir_bridge import FHIRBridge
from .identity import TokenVerifier
from .operations23 import ShiftHandoff, QueueJob
from .engagement24 import Engagement
from .communications.service import CommunicationService
from .communications.api import build_router as communication_router
from .application.access_control import AccessControl
from .application.access_administration import AccessAdministration
from .application.case_queries import CaseQueries
from .application.fhir_use_cases import FHIRUseCases
from .application.engagement_use_cases import EngagementUseCases
from .application.handoffs import HandoffUseCases
from .application.monitoring import MonitoringUseCases
from .application.clinical_cases import ClinicalCases
from .application.agent_execution import AgentExecution
from .application.dispatch_operations import DispatchOperations
from .presentation.auth import make_dependencies
from .presentation.routers.case_queries import build_router as case_queries_router
from .presentation.routers.fhir import build_router as fhir_router
from .presentation.routers.engagement import build_router as engagement_router
from .presentation.routers.handoffs import build_router as handoffs_router
from .presentation.routers.monitoring import build_router as monitoring_router
from .presentation.routers.clinical_cases import build_router as clinical_cases_router
from .presentation.routers.agent_execution import build_router as agent_execution_router
from .presentation.routers.dispatch_operations import build_router as dispatch_operations_router
from .presentation.routers.system_admin import build_router as system_admin_router
from .infrastructure.checkin_dispatcher import N8NCheckinDispatcher
from .infrastructure.case_dispatcher import N8NCaseDispatcher
from .infrastructure.persistence.checkin_reader import SqlCheckinReader
from .infrastructure.persistence.health_reader import SqlHealthReader
from .infrastructure.persistence.coordination_repository import SqlCoordinationRepository
from .infrastructure.persistence.engagement_repository import SqlEngagementRepository
from .infrastructure.persistence.fhir_repository import SqlFhirRepository
from .infrastructure.persistence.handoff_repository import SqlHandoffRepository
from .infrastructure.persistence.dispatch_repository import SqlDispatchRepository
from .infrastructure.persistence.communications_repository import CommunicationsRepository

log=logging.getLogger('hah')
logging.basicConfig(level=logging.WARNING)

def create_app(settings=None, model=None, store=None, dispatch=None, checkin_dispatch=None):
    settings=settings or Settings.from_env()
    settings.validate()
    store=store or Store(settings)
    model=model or LLMClient(settings)
    rag=Rag(store,model,settings.knowledge_dir)
    coordination=Coordinator(store,repository=SqlCoordinationRepository(store))
    fhir_bridge=FHIRBridge(store,coordination,repository=SqlFhirRepository(store))
    verifier=TokenVerifier(settings)
    operations=ShiftHandoff(store,coordination,repository=SqlHandoffRepository(store))
    dispatch_queue=QueueJob(store,repository=SqlDispatchRepository(store))
    engagement=Engagement(store,coordination,repository=SqlEngagementRepository(store))
    communications=CommunicationService(store,coordination,repository=CommunicationsRepository(store))
    case_dispatcher=N8NCaseDispatcher(settings,dispatch)
    checkin_dispatcher=N8NCheckinDispatcher(settings,checkin_dispatch)

    access_policy=AccessControl(store,settings.auth_mode)
    auth_http,clinician,patient,admin=make_dependencies(settings,verifier,access_policy)
    internal=auth_http.internal
    auth=auth_http.auth
    access=auth_http.require_patient
    allowed_patient_refs=auth_http.allowed_patient_refs

    cases=ClinicalCases(store,coordination,operations,dispatch_queue,case_dispatcher,assess)
    agents=AgentExecution(cases,store,coordination,model,rag,assess)
    ops=DispatchOperations(store,coordination,dispatch_queue,operations,case_dispatcher,
                           checkin_dispatcher,SqlCheckinReader(store),SqlHealthReader(store),settings.auth_mode)

    app=FastAPI(title='Hospital-at-Home Care Coordination (Synthetic Research Platform)',version='3.3.0')
    # Preserve existing fixtures and runtime observability against these concrete adapters.
    app.state.communications=communications
    app.state.store=store
    app.state.rag=rag
    app.state.model=model
    app.state.coordination=coordination
    app.state.fhir_bridge=fhir_bridge
    app.state.verifier=verifier
    app.state.operations=operations
    app.state.dispatch_queue=dispatch_queue
    app.state.engagement=engagement
    app.state.clinical_cases=cases
    app.state.agent_execution=agents
    app.state.dispatch_operations=ops

    app.include_router(system_admin_router(AccessAdministration(store),admin,store,model,settings))
    app.include_router(clinical_cases_router(cases,patient,clinician,access))
    app.include_router(agent_execution_router(agents,internal))
    app.include_router(dispatch_operations_router(ops,cases,internal))
    app.include_router(monitoring_router(MonitoringUseCases(store,coordination,operations,
        dispatch_queue,settings,checkin_dispatcher),patient,clinician,auth,internal,access,allowed_patient_refs))
    app.include_router(handoffs_router(HandoffUseCases(operations,coordination,dispatch_queue,settings),
        clinician,access,allowed_patient_refs))
    app.include_router(case_queries_router(CaseQueries(store),clinician,access,allowed_patient_refs))
    app.include_router(fhir_router(FHIRUseCases(fhir_bridge),clinician,internal,access))
    app.include_router(engagement_router(EngagementUseCases(engagement),clinician,patient,internal,
        access,allowed_patient_refs))
    app.include_router(communication_router(communications,clinician,patient,internal,access))
    return app

# Runtime import is expected to validate application secret configuration.
app=create_app()
