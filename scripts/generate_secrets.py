"""Run once, paste output into .env. Do not commit secrets."""
import secrets
from cryptography.fernet import Fernet
for name in ("APP_INTERNAL_KEY", "APP_TOKEN_SECRET", "N8N_ENCRYPTION_KEY", "APP_ADMIN_KEY", "POSTGRES_PASSWORD"):
    print(f"{name}={secrets.token_hex(32)}")
print(f"APP_ENCRYPTION_KEY={Fernet.generate_key().decode()}")
