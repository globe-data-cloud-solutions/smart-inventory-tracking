FROM python:3.12-slim

WORKDIR /app

# shared package — installed as editable so imports resolve as shared.*
COPY backend/shared /app/shared
RUN pip install --no-cache-dir uv && uv pip install --system -e /app/shared

# service files land at /app root — imports like rom routers import ... resolve directly
COPY backend/services/notification-service/ /app/

# install service-level deps (uvicorn, httpx, etc.) from pyproject.toml if present
RUN if [ -f /app/pyproject.toml ]; then uv pip install --system -e /app; fi

ENV PYTHONPATH=/app
EXPOSE 8000

ENTRYPOINT ["sh", "-c", "python -m shared.utils.env_guard && exec \"$@\"", "guard"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
