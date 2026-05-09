FROM python:3.12-slim
WORKDIR /app
COPY backend/shared /app/shared
COPY backend/services/product-service /app/service
RUN pip install --no-cache-dir uv && \
    uv pip install --system -e /app/shared && \
    uv pip install --system -e /app/service
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
