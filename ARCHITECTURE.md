# TraderCat Standalone Pipeline - Complete Separation Architecture

## Summary

The TraderCat pipeline has been **completely separated** from the API service, creating two independent services that communicate only through a shared database.

## Architecture Diagram

```
┌───────────────────────────────────────────────────────────────────────────┐
│                         TraderCat System                                  │
└───────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────┐          ┌─────────────────────────────────┐
│     API Service             │          │     Pipeline Worker             │
│  (tradercat.main:app)       │          │  (tradercat.pipeline.runner)    │
├─────────────────────────────┤          ├─────────────────────────────────┤
│ RUN_MODE: api-only          │          │ RUN_MODE: scheduler             │
│ Entry: uvicorn main:app     │          │ Entry: python -m ...runner      │
│ Port: 8000                  │          │ Port: None (no HTTP)            │
├─────────────────────────────┤          ├─────────────────────────────────┤
│ Components:                 │          │ Components:                     │
│  ├─ FastAPI app             │          │  ├─ APScheduler (cron)          │
│  ├─ REST endpoints          │          │  ├─ Signal workers              │
│  ├─ Authentication          │          │  ├─ Report workers              │
│  ├─ API request handling    │          │  ├─ Market day checking         │
│  └─ Manual pipeline trigger │          │  └─ Orchestrator                │
│      (via orchestrator)     │          │                                 │
├─────────────────────────────┤          ├─────────────────────────────────┤
│ Does NOT import:            │          │ Does NOT have:                  │
│  ✗ scheduler.py             │          │  ✗ FastAPI                      │
│  ✗ APScheduler              │          │  ✗ HTTP endpoints               │
│                             │          │  ✗ API authentication           │
└──────────────┬──────────────┘          └──────────────┬──────────────────┘
               │                                        │
               │                                        │
               ├────────────────────┬───────────────────┤
               │                    │                   │
               ▼                    ▼                   ▼
        ┌──────────────────────────────────────────────────┐
        │            PostgreSQL Database                    │
        ├──────────────────────────────────────────────────┤
        │  Shared Data:                                    │
        │   ├─ Users & API Keys                            │
        │   ├─ Watchlists                                  │
        │   ├─ Signal Records                              │
        │   ├─ Reports                                     │
        │   ├─ Pipeline Runs (state)                       │
        │   └─ Strategy Configs                            │
        │                                                  │
        │  Communication: Database only                    │
        │  No RPC, no shared memory, no message queue     │
        └──────────────────────────────────────────────────┘
```

## Separation Principles

### 1. No Code Sharing
- **API Service**: Never imports `scheduler.py`
- **Pipeline Worker**: Never imports FastAPI code
- **Result**: Zero coupling between services

### 2. Single Entry Point Per Service
- **API**: `python -m uvicorn tradercat.main:app`
- **Pipeline**: `python -m tradercat.pipeline.runner`
- **Result**: Clear service boundaries

### 3. Database-Only Communication
- No HTTP calls between services
- No RPC or message queues (in MVP)
- State stored in PostgreSQL
- **Result**: Simple, reliable communication

### 4. Independent Lifecycle
- Each service starts/stops independently
- No cascading failures
- **Result**: Better reliability

## Deployment Modes

| Mode | Service | Scheduler? | Use Case |
|------|---------|-----------|----------|
| `api-only` | API | ❌ NO | Production API (recommended) |
| `scheduler` | Pipeline | ✅ YES | Production worker (recommended) |
| `combined` | API | ⚠️ YES | Development only (not recommended) |

## Code Flow

### API Service (api-only)

```python
# main.py lifespan
if settings.run_mode == "api-only":
    # NO scheduler import
    logger.info("Pipeline scheduler disabled")
    logger.info("Manual triggers available")
```

Manual trigger flow:
```
User → API endpoint → PipelineOrchestrator.run_pipeline()
                       ↓
                   Database (PipelineRun)
```

### Pipeline Worker (scheduler)

```python
# runner.py
scheduler = get_scheduler()  # ← Only place scheduler is used
scheduler.start()

# Scheduled job runs at 8 PM ET
async def run_scheduled_pipeline():
    orchestrator = PipelineOrchestrator()
    await orchestrator.run_pipeline(today)
```

Scheduled flow:
```
APScheduler cron → PipelineScheduler → Orchestrator → Workers
                                          ↓
                                      Database
```

## Production Deployment

### Docker Compose (Recommended)

```yaml
services:
  api:
    environment:
      RUN_MODE: api-only
    ports:
      - "8000:8000"
    replicas: 3  # Scale independently
  
  pipeline-worker:
    dockerfile: Dockerfile.pipeline
    environment:
      RUN_MODE: scheduler
    replicas: 1  # Single scheduler
```

### Kubernetes

```yaml
---
# API: Multiple replicas for load
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tradercat-api
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: api
        image: tradercat:latest
        env:
        - name: RUN_MODE
          value: "api-only"

---
# Pipeline: Single replica (scheduler)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tradercat-pipeline
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: pipeline
        image: tradercat-pipeline:latest
        env:
        - name: RUN_MODE
          value: "scheduler"
```

## Benefits of Complete Separation

### Before (Combined Mode)
```
Single Container
├─ API requests } compete for
├─ Pipeline jobs } CPU/memory
└─ Scheduler     }
```
❌ Resource contention
❌ API slowdowns during pipeline
❌ Cascading failures
❌ Difficult to scale

### After (Separated Services)
```
API Container          Pipeline Container
├─ API only            ├─ Scheduler only
└─ No competition      └─ No API overhead
```
✅ Isolated resources
✅ Independent scaling
✅ No API impact from pipeline
✅ Clear boundaries

## Monitoring

### API Service
```bash
# Health check
curl http://localhost:8000/api/admin/system/health

# Logs
docker logs tradercat-api

# Metrics
- Request latency
- Error rate
- Active connections
```

### Pipeline Worker
```bash
# Process status (exit code 0 = healthy)
docker ps | grep tradercat-pipeline

# Logs
docker logs tradercat-pipeline

# Metrics
- Pipeline completion time
- Success/failure rate
- Symbols processed
```

## Troubleshooting

### Issue: Scheduler not running

**Check RUN_MODE**:
```bash
docker exec tradercat-pipeline env | grep RUN_MODE
# Should be: RUN_MODE=scheduler
```

**Check correct entry point**:
```bash
docker exec tradercat-pipeline ps aux | grep python
# Should see: python -m tradercat.pipeline.runner
```

### Issue: API is slow

**Verify API is not running scheduler**:
```bash
docker logs tradercat-api | grep scheduler
# Should see: "Pipeline scheduler disabled"
```

### Issue: Manual triggers not working

**Manual triggers use orchestrator, not scheduler**:
```bash
# This works even with RUN_MODE=api-only
curl -X POST http://localhost:8000/api/admin/pipeline/trigger
```

## Migration from Combined Mode

### Step 1: Update docker-compose.yml
```yaml
# Add RUN_MODE to api service
api:
  environment:
    RUN_MODE: api-only  # ← Add this

# Add new pipeline-worker service
pipeline-worker:
  build:
    dockerfile: Dockerfile.pipeline
  environment:
    RUN_MODE: scheduler
```

### Step 2: Deploy
```bash
docker-compose up -d
```

### Step 3: Verify
```bash
# API should not have scheduler
docker logs tradercat-api | grep "Pipeline scheduler disabled"

# Pipeline should have scheduler
docker logs tradercat-pipeline | grep "Pipeline scheduler started"
```

## FAQ

**Q: Can API and pipeline run on different machines?**
A: Yes! They only need database connectivity.

**Q: Can I run multiple pipeline workers?**
A: Yes, but ensure only ONE has scheduler enabled (RUN_MODE=scheduler).
   Others can run on-demand with manual triggers.

**Q: What if pipeline crashes?**
A: API continues working. Restart pipeline service independently.

**Q: How do I trigger pipeline manually?**
A: Use API endpoint: `POST /api/admin/pipeline/trigger`
   Works in all modes (api-only, scheduler, combined).

**Q: Is combined mode deprecated?**
A: No, but not recommended for production. Use for development only.

## References

- **Deployment Guide**: See `DEPLOYMENT.md` for detailed instructions
- **API Documentation**: `http://localhost:8000/docs`
- **Docker Compose**: `docker-compose.yml`
- **Pipeline Dockerfile**: `Dockerfile.pipeline`
