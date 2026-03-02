# TraderCat Deployment Guide

## Overview

TraderCat is deployed as **four services** that communicate exclusively through a shared PostgreSQL database:

| Service | Container | Port | Entry Point |
|---------|-----------|------|-------------|
| **PostgreSQL** | `tradercat-postgres` | 5432 | — |
| **API** | `tradercat-api` | 8000 | `uvicorn tradercat.main:app` |
| **Pipeline Worker** | `tradercat-pipeline` | — | `python -m tradercat.pipeline.runner` |
| **Web** | `tradercat-web` | 3000 | `node server.js` (Next.js standalone) |

Benefits of this separation:
- ✅ **Complete code isolation**: API never imports scheduler code
- ✅ **Independent scaling**: Scale API and web separately from pipeline
- ✅ **Isolated resource usage**: No resource contention
- ✅ **No API downtime**: Pipeline runs don't affect API or frontend
- ✅ **Easier monitoring**: Separate logs and metrics
- ✅ **Flexible deployment**: Deploy services independently

## Architecture

```
┌───────────────────┐
│  Web (Next.js)    │
│  Port 3000        │──── browser calls ────┐
│  tradercat-web    │                       │
└───────────────────┘                       ▼
                              ┌─────────────────────────┐     ┌──────────────────┐
                              │  API Service            │────▶│    PostgreSQL    │
                              │  Port 8000              │     │    Port 5432     │
                              │  RUN_MODE=api-only      │     │                  │
                              │                         │     │  Shared Database │
                              │  ├── FastAPI app        │     │                  │
                              │  ├── REST endpoints     │     └────────▲─────────┘
                              │  ├── Manual triggers    │              │
                              │  └── NO scheduler code  │              │
                              └─────────────────────────┘              │
                                                          ┌────────────┴────────────┐
                                                          │  Pipeline Worker        │
                                                          │  No HTTP port           │
                                                          │  RUN_MODE=scheduler     │
                                                          │                         │
                                                          │  ├── APScheduler        │
                                                          │  ├── Orchestrator       │
                                                          │  ├── Signal workers     │
                                                          │  └── Report workers     │
                                                          └─────────────────────────┘
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

**Full stack** (Database + API + Pipeline + Web):
```bash
docker compose up -d
```

This starts:
- PostgreSQL database (port 5432)
- API service (port 8000, `RUN_MODE=api-only`)
- Pipeline worker (`RUN_MODE=scheduler`, runs at 8 PM ET)
- Web frontend (port 3000, Next.js standalone)

**API + Web only** (no pipeline):
```bash
docker compose up -d postgres api web
```

**Backend only** (no frontend):
```bash
docker compose up -d postgres api pipeline-worker
```

**Check status**:
```bash
docker compose ps
docker compose logs -f api
docker compose logs -f web
docker compose logs -f pipeline-worker
```

### Option 2: Kubernetes

Example K8s deployments:

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
# web-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tradercat-web
spec:
  replicas: 2
  template:
    spec:
      containers:
      - name: web
        image: tradercat-web:latest
        ports:
        - containerPort: 3000
        env:
        - name: HOSTNAME
          value: "0.0.0.0"

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
PIPELINE_AUDIT_BATCH_SIZE=5
PIPELINE_EXEC_BATCH_SIZE=5
PIPELINE_LLM_MAX_RETRIES=0
DEFAULT_LLM_MODEL=claude-opus-4.6
DEFAULT_LLM_PROVIDER=copilot
LLM_MAX_TOKENS_P2=4096
LLM_MAX_TOKENS_P3A=2048
LLM_MAX_TOKENS_P3B=4096
LLM_MAX_TOKENS_P4=8192
LLM_STREAMING_ENABLED=true
LOG_FORMAT=json
LOG_LEVEL=INFO
```

#### Web Frontend
```bash
# Build-time only (baked into the JS bundle)
NEXT_PUBLIC_API_URL=http://localhost:8000   # or https://api.example.com in prod
```

## Manual Pipeline Triggers

Even with `RUN_MODE=api-only`, you can manually trigger the pipeline via API:

```bash
curl -X POST http://localhost:8000/api/admin/pipeline/trigger \
  -H "Authorization: Bearer <jwt>"
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

All services write structured JSON logs:
```bash
docker compose logs -f api
docker compose logs -f web
docker compose logs -f pipeline-worker
```

### Graceful Shutdown

Pipeline worker handles SIGTERM/SIGINT gracefully:
```bash
docker compose stop pipeline-worker  # Waits for current jobs
```

## Scaling

### Horizontal Scaling

**API**: Scale to N replicas
```bash
docker compose up -d --scale api=3
```

**Web**: Scale to N replicas
```bash
docker compose up -d --scale web=2
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
  
  web:
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
  
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

1. **Use separate services** (`api-only` + `scheduler` + `web`)
2. **Run 1 pipeline worker** (avoid duplicate schedules)
3. **Scale API and Web independently** (3+ replicas behind load balancer)
4. **Set `NEXT_PUBLIC_API_URL`** to the production API domain when building the web image
5. **Set resource limits** (prevent resource exhaustion)
6. **Monitor exit codes** (pipeline worker health)
7. **Enable structured logging** (`LOG_FORMAT=json`)
8. **Use secrets management** (for `DATABASE_URL`, `JWT_SECRET`, API tokens)
9. **Change `JWT_SECRET`** from the default in production

## Security Notes

- Pipeline worker does NOT expose HTTP ports
- Only API and Web services should be internet-facing
- API and Pipeline require database access; Web only calls the API
- `NEXT_PUBLIC_API_URL` is baked into the JS bundle at build time — rebuild the web image when the API URL changes
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
- Check logs: `docker compose logs`
- GitHub Issues: https://github.com/AimeSoleil/TraderCat/issues
- API Documentation: http://localhost:8000/docs
- Web Frontend: http://localhost:3000
