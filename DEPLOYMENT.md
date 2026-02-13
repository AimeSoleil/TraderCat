# TraderCat Standalone Pipeline Deployment Guide

## Overview

The TraderCat pipeline is **completely separated** from the API service. This provides:
- ✅ **Complete code isolation**: API never imports scheduler code
- ✅ **Independent scaling**: Scale API and pipeline separately
- ✅ **Isolated resource usage**: No resource contention
- ✅ **No API downtime**: Pipeline runs don't affect API
- ✅ **Easier monitoring**: Separate logs and metrics
- ✅ **Flexible deployment**: Deploy services independently

## Architecture

```
┌─────────────────────────┐     ┌──────────────────┐     ┌─────────────────────────┐
│  API Service            │────▶│    PostgreSQL    │◀────│  Pipeline Worker        │
│  (main.py)              │     │                  │     │  (pipeline.runner)      │
│  RUN_MODE=api-only      │     │  Shared Database │     │  RUN_MODE=scheduler     │
│                         │     │                  │     │                         │
│  ├── FastAPI app        │     │  Communication:  │     │  ├── APScheduler        │
│  ├── REST endpoints     │     │  Database only   │     │  ├── Orchestrator       │
│  ├── Manual triggers    │     │                  │     │  ├── Signal workers     │
│  └── NO scheduler code  │     │                  │     │  └── Report workers     │
└─────────────────────────┘     └──────────────────┘     └─────────────────────────┘
                                                           
                                                           COMPLETE SEPARATION:
                                                           - Different entry points
                                                           - No shared scheduler state
                                                           - Independent processes
```

## Complete Separation Design

### API Service (`RUN_MODE=api-only`)
- **Entry Point**: `python -m uvicorn tradercat.main:app`
- **Scheduler Code**: NEVER imported
- **Pipeline Execution**: Manual triggers only (via `/api/admin/pipeline/trigger`)
- **Uses**: `PipelineOrchestrator` directly (not scheduler)

### Pipeline Worker (`RUN_MODE=scheduler`)
- **Entry Point**: `python -m tradercat.pipeline.runner`
- **Scheduler Code**: Exclusively owned by this service
- **Pipeline Execution**: Automatic via APScheduler cron
- **No API**: Does not expose HTTP endpoints

### Communication
- **Database**: Only communication channel
- **No RPC**: Services don't call each other
- **Async**: Pipeline runs asynchronously from API

## Deployment Modes

### RUN_MODE Configuration

The `RUN_MODE` environment variable enforces complete separation:

| Mode | Entry Point | Scheduler Imported? | Use Case |
|------|-------------|---------------------|----------|
| `api-only` | `main.py` | ❌ NO | **Production API** (recommended) |
| `scheduler` | `pipeline.runner` | ✅ YES | **Production Pipeline** (recommended) |
| `combined` | `main.py` | ⚠️ YES | **Development only** (not recommended) |

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
