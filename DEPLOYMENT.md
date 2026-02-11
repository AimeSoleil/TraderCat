# TraderCat Standalone Pipeline Deployment Guide

## Overview

The TraderCat pipeline can now be deployed as a **standalone service** separate from the API. This provides:
- ✅ Independent scaling
- ✅ Isolated resource usage
- ✅ No API downtime during pipeline execution
- ✅ Easier monitoring and debugging
- ✅ Flexible deployment options

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  API Service    │────▶│    PostgreSQL    │◀────│  Pipeline Worker│
│  (port 8000)    │     │                  │     │  (cron scheduler)│
│  - REST API     │     │  Shared Database │     │  - Signal gen   │
│  - Manual       │     │                  │     │  - Report gen   │
│    triggers     │     │                  │     │  - Scheduled    │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

## Deployment Modes

### RUN_MODE Configuration

The `RUN_MODE` environment variable controls how services run:

| Mode | Description | Use Case |
|------|-------------|----------|
| `api-only` | API without scheduler | Production API service |
| `scheduler` | Pipeline worker only | Production pipeline worker |
| `combined` | Both API + scheduler | Development, legacy deployments |

## Deployment Options

### Option 1: Docker Compose (Recommended)

**Full deployment** (API + Pipeline + Database):
```bash
docker-compose up -d
```

This starts:
- PostgreSQL database
- API service (port 8000, RUN_MODE=api-only)
- Pipeline worker (RUN_MODE=scheduler, runs at 8 PM ET)

**API only** (without pipeline):
```bash
docker-compose up -d postgres api
```

**Check status**:
```bash
docker-compose ps
docker-compose logs -f pipeline-worker
```

### Option 2: Kubernetes

Example K8s deployment:

```yaml
# api-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tradercat-api
spec:
  replicas: 3  # Scale API independently
  template:
    spec:
      containers:
      - name: api
        image: tradercat:latest
        env:
        - name: RUN_MODE
          value: "api-only"
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: tradercat-secrets
              key: database-url

---
# pipeline-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tradercat-pipeline
spec:
  replicas: 1  # Single scheduler instance
  template:
    spec:
      containers:
      - name: pipeline
        image: tradercat:latest
        args: ["python", "-m", "tradercat.pipeline.runner"]
        env:
        - name: RUN_MODE
          value: "scheduler"
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: tradercat-secrets
              key: database-url
```

### Option 3: Standalone Script

Run pipeline worker directly:
```bash
export RUN_MODE=scheduler
export DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/tradercat
python -m tradercat.pipeline.runner
```

### Option 4: Legacy Mode (Single Container)

```bash
export RUN_MODE=combined
docker-compose up -d postgres api
```

## Configuration

### Environment Variables

#### API Service
```bash
RUN_MODE=api-only
DATABASE_URL=postgresql+asyncpg://tradercat:tradercat@postgres:5432/tradercat
LOG_FORMAT=json
LOG_LEVEL=INFO
```

#### Pipeline Worker
```bash
RUN_MODE=scheduler
DATABASE_URL=postgresql+asyncpg://tradercat:tradercat@postgres:5432/tradercat
PIPELINE_SCHEDULE_HOUR=20
PIPELINE_TIMEZONE=America/New_York
PIPELINE_MAX_CONCURRENCY=5
TRADERCAT_AI_TOKEN=your_token_here
DEFAULT_LLM_MODEL=gpt-4o
DEFAULT_PERSONA=wyckoff
LOG_FORMAT=json
LOG_LEVEL=INFO
```

## Manual Pipeline Triggers

Even with `RUN_MODE=api-only`, you can manually trigger the pipeline via API:

```bash
curl -X POST http://localhost:8000/api/admin/pipeline/trigger \
  -H "X-API-Key: your_admin_api_key"
```

## Monitoring

### Health Checks

**API Health**:
```bash
curl http://localhost:8000/api/admin/system/health
```

**Pipeline Health**:
- Monitor process exit codes (0 = success)
- Check container logs: `docker-compose logs pipeline-worker`
- Query pipeline status via API: `GET /api/admin/pipeline/status`

### Logging

Both services write structured JSON logs to `/app/logs`:
```bash
docker-compose logs -f api
docker-compose logs -f pipeline-worker
```

### Graceful Shutdown

Pipeline worker handles SIGTERM/SIGINT gracefully:
```bash
docker-compose stop pipeline-worker  # Waits for current jobs
```

## Scaling

### Horizontal Scaling

**API**: Scale to N replicas
```bash
docker-compose up -d --scale api=3
```

**Pipeline**: Keep at 1 replica (scheduler should run once)
```bash
# In K8s, use a single replica deployment or CronJob
```

### Resource Limits

**docker-compose.yml**:
```yaml
services:
  api:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 1G
  
  pipeline-worker:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
```

## Troubleshooting

### Pipeline Not Running

1. Check RUN_MODE:
   ```bash
   docker exec tradercat-pipeline env | grep RUN_MODE
   ```

2. Check logs:
   ```bash
   docker logs tradercat-pipeline
   ```

3. Verify schedule:
   ```bash
   docker logs tradercat-pipeline | grep "Next scheduled run"
   ```

### Database Connection Issues

Both services need access to PostgreSQL:
```bash
docker exec tradercat-pipeline pg_isready -h postgres -U tradercat
```

### Manual Test

Test pipeline runner directly:
```bash
docker exec -it tradercat-pipeline python -m tradercat.pipeline.runner
```

## Migration Guide

### From Combined Mode

**Before** (single container):
```yaml
services:
  api:
    environment:
      # No RUN_MODE (defaults to combined)
```

**After** (separate services):
```yaml
services:
  api:
    environment:
      RUN_MODE: api-only
  
  pipeline-worker:
    build:
      dockerfile: Dockerfile.pipeline
    environment:
      RUN_MODE: scheduler
```

## Production Recommendations

1. **Use separate services** (`api-only` + `scheduler`)
2. **Run 1 pipeline worker** (avoid duplicate schedules)
3. **Scale API independently** (3+ replicas behind load balancer)
4. **Set resource limits** (prevent resource exhaustion)
5. **Monitor exit codes** (pipeline worker health)
6. **Enable structured logging** (`LOG_FORMAT=json`)
7. **Use secrets management** (for DATABASE_URL, API tokens)

## Security Notes

- Pipeline worker does NOT expose HTTP ports
- Only API service should be internet-facing
- Both services require database access
- Use network policies in K8s to restrict traffic

## Performance

### Before (Combined)
- API requests compete with pipeline for CPU/memory
- Pipeline execution can cause API slowdowns
- Single container scaling limited

### After (Separate)
- API performance unaffected by pipeline
- Independent resource allocation
- Scale API to meet demand without over-provisioning for pipeline

## Support

For issues or questions:
- Check logs: `docker-compose logs`
- GitHub Issues: https://github.com/AimeSoleil/TraderCat/issues
- API Documentation: http://localhost:8000/docs
