FROM python:3.12-slim

WORKDIR /app

# shared package — mirrors repo layout so seed_permissions.py's relative
# sys.path (scripts/../backend) resolves to /app/backend
COPY backend/shared /app/backend/shared
RUN pip install --no-cache-dir uv && uv pip install --system -e /app/backend/shared \n    && uv pip install --system "bcrypt>=4.0.0"

COPY backend/migrations /app/backend/migrations
COPY scripts/seed_permissions.py /app/scripts/seed_permissions.py

ENV PYTHONPATH=/app/backend
WORKDIR /app/backend/migrations

CMD ["sh", "-c", "alembic upgrade head && alembic current && python /app/scripts/seed_permissions.py"]
