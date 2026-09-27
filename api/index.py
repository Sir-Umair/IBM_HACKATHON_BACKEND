import sys
import os
from pathlib import Path

# Add project root and current dir to sys.path so 'app' and its modules are always discoverable
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent

for p in [str(project_root), str(current_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app.main import app
from app.database import ensure_db_ready

# Ensure tables and seed data are ready on serverless cold start
try:
    ensure_db_ready()
except Exception:
    pass

# Export for Vercel Serverless Function compatibility
handler = app
