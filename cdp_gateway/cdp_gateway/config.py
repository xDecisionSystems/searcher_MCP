import os
from pathlib import Path

CDP_URL = os.getenv("BROWSER_WORKER_CDP_URL", "http://127.0.0.1:9222")
GATEWAY_PORT = int(os.getenv("CDP_GATEWAY_PORT", "8020"))

# Secret used to sign JWTs. Generate with:
#   python3 -c "import secrets; print(secrets.token_urlsafe(48))"
JWT_SECRET = os.getenv("CDP_JWT_SECRET", "")

# Path to the bcrypt password hash file — created at runtime when password is first set.
# Not committed to git. Root can see the hash but cannot reverse it.
PASSWORD_FILE = Path(os.getenv("CDP_PASSWORD_FILE", "/opt/repo/cdp_gateway/password.hash"))

DURATIONS = {
    "30min": 30 * 60,
    "60min": 60 * 60,
    "24hr":  24 * 60 * 60,
}
