"""
Global constants for LockBox.
Change VAULT_PATH if you want the vault stored somewhere else.
"""
from pathlib import Path

BASE_DIR        = Path(__file__).parent.parent
VAULT_PATH      = BASE_DIR / "vault.enc"
PBKDF2_ITER     = 600_000
SALT_SIZE       = 32        # bytes
KEY_SIZE        = 32        # bytes
APP_NAME        = "LockBox"
APP_VERSION     = "1.0.0"
SESSION_TIMEOUT = 300       # seconds — auto-lock after 5 min idle