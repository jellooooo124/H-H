import os,sys,pathlib,secrets
from cryptography.fernet import Fernet
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
os.environ.setdefault('APP_INTERNAL_KEY','int-'+secrets.token_hex(32))
os.environ.setdefault('APP_TOKEN_SECRET','jwt-'+secrets.token_hex(32))
os.environ.setdefault('APP_ENCRYPTION_KEY',Fernet.generate_key().decode())
os.environ.setdefault('DB_PATH','/tmp/hah-module-default.db')
os.environ.setdefault('KNOWLEDGE_DIR',str(ROOT/'knowledge'))
os.environ.setdefault('DEMO_MODE','true')
