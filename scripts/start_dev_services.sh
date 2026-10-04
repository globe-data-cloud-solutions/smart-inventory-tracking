#!/bin/bash
# Start all backend services with local development environment variables

set -e

# Kill existing processes
echo "Stopping any running services..."
pkill -9 -f "uvicorn|python.*main:app" 2>/dev/null || true
sleep 3

# Set environment variables
export DATABASE_URL="postgresql+asyncpg://smart_user:smart_local_pass@localhost:5432/smart_dev"
export DATABASE_READ_URL="postgresql+asyncpg://smart_user:smart_local_pass@localhost:5432/smart_dev"
export JWT_SECRET="local-dev-secret-key-not-for-production"
export ENVIRONMENT="local"
export REDIS_URL="redis://localhost:6379/0"
export PYTHONUNBUFFERED=1

echo "Environment: ENVIRONMENT=$ENVIRONMENT"
echo "Database: $DATABASE_URL"
echo ""

# Start services sequentially with delays
start_service() {
  local service=$1
  local port=$2
  echo "Starting $service on port $port..."
  (
    cd "/c/git-repos/smart-platform/backend/services/$service"
    python -m uvicorn main:app --host 0.0.0.0 --port $port
  ) > "/tmp/${service}.log" 2>&1 &
  sleep 15
  echo "  ...waiting for port $port to be ready"
  for i in {1..10}; do
    if curl -s http://localhost:$port/docs > /dev/null 2>&1; then
      echo "  OK: $service is ready"
      return 0
    fi
    sleep 2
  done
  echo "  WARNING: $service may not be ready yet"
}

# Start each service
start_service "auth-service" 8004
start_service "tenant-service" 8001
start_service "product-service" 8003
start_service "inventory-service" 8002

# Start API Gateway
echo "Starting API Gateway on port 8000..."
(
  cd "/c/git-repos/smart-platform/backend/services/api-gateway"
  INVENTORY_SERVICE_URL="http://localhost:8002" \
  TENANT_SERVICE_URL="http://localhost:8001" \
  PRODUCT_SERVICE_URL="http://localhost:8003" \
  AUTH_SERVICE_URL="http://localhost:8004" \
  python -m uvicorn main:app --host 0.0.0.0 --port 8000
) > /tmp/api-gateway.log 2>&1 &

sleep 15

echo ""
echo "================================"
echo "All services started!"
echo "================================"
echo ""
echo "API Gateway:      http://localhost:8000"
echo "Auth Service:     http://localhost:8004"
echo "Tenant Service:   http://localhost:8001"
echo "Product Service:  http://localhost:8003"
echo "Inventory Service: http://localhost:8002"
echo ""
echo "Testing login endpoint..."
curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"dev_email":"admin@t01.com"}' | jq .access_token 2>/dev/null | head -c 30 && echo "..." || echo "FAILED"
