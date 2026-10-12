import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    internal_key: str
    jwt_secret: str
    encryption_key: str
    openai_key: str
    llm_model: str
    vision_model: str
    embedding_model: str
    webhook_url: str
    database_path: str
    knowledge_dir: str
    demo_mode: bool
    database_url: str = ""
    auth_mode: str = "demo"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_clinician_group: str = "hah-clinician"
    oidc_patient_group: str = "hah-patient"
    admin_key: str = ""

    @classmethod
    def from_env(cls):
        return cls(
            internal_key=os.getenv('APP_INTERNAL_KEY', ''),
            jwt_secret=os.getenv('APP_TOKEN_SECRET', ''),
            encryption_key=os.getenv('APP_ENCRYPTION_KEY', ''),
            openai_key=os.getenv('OPENAI_API_KEY', ''),
            llm_model=os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'),
            vision_model=os.getenv('OPENAI_VISION_MODEL', 'gpt-4.1-mini'),
            embedding_model=os.getenv('OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small'),
            webhook_url=os.getenv('N8N_WEBHOOK_URL', 'http://n8n:5678/webhook/hah-case-intake'),
            database_path=os.getenv('DB_PATH', '/tmp/hah-demo.db'),
            knowledge_dir=os.getenv('KNOWLEDGE_DIR', 'knowledge'),
            demo_mode=os.getenv('DEMO_MODE', 'true').lower() == 'true',
            database_url=os.getenv('DATABASE_URL',''),
            auth_mode=os.getenv('AUTH_MODE','demo').lower(),
            oidc_issuer=os.getenv('OIDC_ISSUER',''),
            oidc_audience=os.getenv('OIDC_AUDIENCE',''),
            oidc_jwks_url=os.getenv('OIDC_JWKS_URL',''),
            oidc_clinician_group=os.getenv('OIDC_CLINICIAN_GROUP','hah-clinician'),
            oidc_patient_group=os.getenv('OIDC_PATIENT_GROUP','hah-patient'),
            admin_key=os.getenv('APP_ADMIN_KEY',''),
        )

    def validate(self):
        if len(self.internal_key) < 32 or len(self.jwt_secret) < 32:
            raise RuntimeError('Configure random APP_INTERNAL_KEY and APP_TOKEN_SECRET (>=32 characters)')
        if not self.encryption_key:
            raise RuntimeError('APP_ENCRYPTION_KEY is required')
        if self.auth_mode not in ('demo','oidc'):
            raise RuntimeError('AUTH_MODE must be demo or oidc')
        if self.auth_mode=='oidc':
            if not (self.oidc_issuer.startswith('https://') and self.oidc_jwks_url.startswith('https://') and self.oidc_audience):
                raise RuntimeError('OIDC requires HTTPS issuer/JWKS URL and exact audience')
            if len(self.admin_key)<32:
                raise RuntimeError('OIDC access assignments require a separate APP_ADMIN_KEY >=32 chars')
        if self.database_url and not self.database_url.startswith(('postgresql://','postgres://')):
            raise RuntimeError('DATABASE_URL must use postgresql://')
        if not self.demo_mode:
            raise RuntimeError('Prototype must remain in DEMO_MODE; production deployment is unsupported')
