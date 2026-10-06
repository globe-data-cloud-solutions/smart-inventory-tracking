import os

# backend/shared/db/session.py (and shared/cache/redis_client.py) read these
# env vars at IMPORT time, not at call time — any test module that transitively
# imports shared.db.session fails at collection if they are unset, even when
# the test itself never touches a real database or Redis connection.
# Obviously-fake localhost defaults let collection succeed; a real value from
# .env (or any other source) always wins since setdefault() never overwrites
# an already-set variable.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://fake:fake@localhost:5432/fake")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://fake:fake@localhost:5432/fake")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
