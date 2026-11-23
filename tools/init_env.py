"""Create .env from .env.example with random secrets. Never overwrites; prints nothing secret."""

import re
import secrets
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
env, example = root / ".env", root / ".env.example"
if env.exists():
    print(".env already exists; left untouched")
    sys.exit(0)
pg = secrets.token_urlsafe(24)
text = example.read_text()
text = text.replace("change-me", pg)
text = re.sub(r"^APP_SECRET_KEY=.*$", f"APP_SECRET_KEY={secrets.token_urlsafe(48)}", text, flags=re.M)
env.write_text(text)
env.chmod(0o600)
print("wrote .env (random POSTGRES_PASSWORD and APP_SECRET_KEY)")
