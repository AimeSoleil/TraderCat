# TraderCat 🐱📈

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://github.com/AimeSoleil/TraderCat/graphs/commit-activity)

**TraderCat** is a **multi-tenant API service** for trading signal generation and AI-powered market analysis. It combines quantitative algorithmic strategies with LLM-driven insights, delivered through a FastAPI-based REST API.

## 🚀 Key Features

### 🏗️ Multi-Tenant Architecture
- **User Management**: Admin-controlled user provisioning with API key authentication
- **Per-User Watchlists**: Track up to 50 symbols per user (configurable)
- **Custom Strategy Parameters**: Users can override default strategy configurations
- **Tenant-Isolated Reports**: Each user gets personalized LLM analysis

### 📊 Signal Generation Engine
- **8 Trading Strategies**: Bollinger Bands, Momentum, Divergence, Fibonacci, Chart Patterns, Candlestick Patterns, Sector Rotation
- **Dual-Scope Signals**: 
  - **Global**: Predefined symbols (SPY, QQQ, etc.) shared across all users
  - **User**: Deduplicated signals for user watchlist symbols
- **Async Processing**: Concurrent signal generation with configurable workers

### 🤖 Nightly Pipeline
- **Market-Day Aware**: Automatically runs at 8 PM ET on trading days only
- **Three-Phase Execution**:
  1. Global signal generation
  2. User-space signal generation (deduplicated)
  3. Per-user LLM report generation
- **Idempotent**: Safe to retry failed runs without duplication

### 🧠 AI Analysis (LLM Integration)
- **Persona-Based Analysis**: Choose from multiple analyst personas (Wyckoff, Buffett, etc.)
- **Context-Aware Reports**: Includes today's signals, past 3 days, and global market context
- **Model Selection**: Configurable LLM models (GPT-4o default)

---

## 📂 Architecture

```text
TraderCat/
├── src/tradercat/
│   ├── main.py                 # FastAPI application
│   ├── config.py               # Pydantic settings
│   ├── database.py             # SQLAlchemy async setup
│   │
│   ├── models/                 # Database models
│   │   ├── user.py             # User, ApiKey
│   │   ├── symbol.py           # WatchlistItem
│   │   ├── signal.py           # SignalRecord
│   │   ├── report.py           # Report
│   │   ├── strategy.py         # StrategyConfig
│   │   └── pipeline.py         # PipelineRun
│   │
│   ├── schemas/                # Pydantic schemas
│   │   ├── user.py
│   │   ├── symbol.py
│   │   ├── signal.py
│   │   ├── report.py
│   │   └── strategy.py
│   │
│   ├── api/                    # FastAPI routers
│   │   ├── deps.py             # Auth & DB injection
│   │   ├── v1/
│   │   │   ├── users.py        # User CRUD (admin)
│   │   │   ├── watchlist.py    # Watchlist management
│   │   │   ├── strategies.py   # Strategy config
│   │   │   ├── signals.py      # Signal queries
│   │   │   └── reports.py      # Report queries
│   │   └── admin/
│   │       ├── pipeline.py     # Pipeline control
│   │       └── system.py       # Health check
│   │
│   ├── core/                   # Business logic
│   │   ├── bot.py              # Signal generation
│   │   ├── strategy/           # Strategy implementations
│   │   └── data/               # Market data providers
│   │
│   ├── pipeline/               # Nightly pipeline
│   │   ├── scheduler.py        # APScheduler
│   │   ├── orchestrator.py     # Pipeline coordinator
│   │   ├── signal_worker.py    # Signal generation
│   │   ├── report_worker.py    # LLM report generation
│   │   └── holidays.py         # Market calendar
│   │
│   └── ai/                     # LLM integration
│       ├── llm_providers.py
│       └── prompts/
│
├── alembic/                    # Database migrations
├── tests/                      # Test suite
├── docker-compose.yml          # Docker orchestration
├── Dockerfile                  # Container image
└── .env.example                # Configuration template
```

---

## 🛠️ Installation

### Prerequisites
- Python 3.10+ 
- PostgreSQL 16+ (or use Docker Compose)
- GitHub Copilot SDK token (for LLM features)

### Local Development

1. **Clone the repository**
   ```bash
   git clone https://github.com/AimeSoleil/TraderCat.git
   cd TraderCat
   ```

2. **Install dependencies**
   ```bash
   pip install -e .
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your database URL and API tokens
   ```

4. **Run database migrations**
   ```bash
   alembic upgrade head
   ```

5. **Start the API**
   ```bash
   python -m uvicorn tradercat.main:app --reload
   ```

### Docker Deployment

```bash
docker-compose up -d
```

The API will be available at `http://localhost:8000`

---

## 🔐 API Authentication

All endpoints (except `/api/admin/system/health`) require API key authentication via the `X-API-Key` header.

### Initial Admin Setup

When you run database migrations for the first time, an initial admin user is automatically created:

```bash
alembic upgrade head
```

This will:
1. Create all database tables
2. Seed an initial admin user with credentials:
   - Username: `admin` (configurable via `ADMIN_USERNAME`)
   - Email: `admin@tradercat.com` (configurable via `ADMIN_EMAIL`)
   - Role: `admin`
3. Generate and display an API key (shown only once)

**Important**: Save the API key displayed during migration! It cannot be retrieved later.

**Customizing Admin User**: Set environment variables before running migrations:
```bash
export ADMIN_USERNAME=myadmin
export ADMIN_EMAIL=admin@mycompany.com
export ADMIN_MAX_SYMBOLS=200
alembic upgrade head
```

### Creating Additional Users

Only admins can create users via the API:

```bash
curl -X POST http://localhost:8000/api/v1/users \
  -H "X-API-Key: your_admin_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "trader1",
    "email": "trader1@example.com",
    "role": "user",
    "max_symbols": 50
  }'
```

The response will include a generated API key for the new user.

---

## 📖 API Endpoints

### User Management (Admin Only)
- `POST /api/v1/users` - Create user + generate API key
- `GET /api/v1/users` - List users
- `GET /api/v1/users/{id}` - Get user details
- `PATCH /api/v1/users/{id}` - Update user

### Watchlist
- `GET /api/v1/watchlist` - List symbols (with filtering)
- `POST /api/v1/watchlist` - Add symbol
- `DELETE /api/v1/watchlist/{symbol}` - Remove symbol

### Strategies
- `GET /api/v1/strategies` - List strategies with defaults & user overrides
- `PUT /api/v1/strategies/{name}` - Update user-level parameters

### Signals
- `GET /api/v1/signals` - Query signals (filters: date, symbol, strategy)
  - Users see GLOBAL signals + USER signals for their watchlist

### Reports
- `GET /api/v1/reports` - List reports (filters: date, symbol, type)
- `GET /api/v1/reports/{id}` - Get full report with context

### Admin: Pipeline
- `POST /api/admin/pipeline/trigger` - Manually trigger pipeline
- `GET /api/admin/pipeline/status` - Get pipeline status

### Admin: System
- `GET /api/admin/system/health` - Health check (public)

**API Documentation**: Visit `/docs` for interactive Swagger UI

---

## 🔄 Pipeline Execution

### Automatic (Scheduled)
The pipeline runs automatically at **8:00 PM Eastern Time** on market days (Monday-Friday, excluding NYSE holidays).

### Manual Trigger
```bash
curl -X POST http://localhost:8000/api/admin/pipeline/trigger \
  -H "X-API-Key: your_admin_api_key"
```

### Pipeline Flow
1. **Global Signals**: Generate signals for SPY, QQQ, DIA, IWM, TLT, XLK, XLF, XLY, XLV, XLE, XLI, XLP
2. **User Signals**: Generate signals for unique symbols across all user watchlists (deduplicated)
3. **Reports**: For each user × each watchlist symbol, generate an LLM analysis report

---

## 🧪 Testing

```bash
# Run all tests
pytest

# Run specific test modules
pytest tests/models/
pytest tests/pipeline/

# With coverage
pytest --cov=tradercat
```

---

## 🐳 Docker

### Standalone Pipeline Deployment

TraderCat now supports **separate API and pipeline services** for production deployments. See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed guide.

**Quick Start** (separate services):
```bash
docker-compose up -d  # Starts API, Pipeline Worker, and PostgreSQL
```

**Architecture**:
- **API Service** (port 8000): REST API only, no scheduler
- **Pipeline Worker**: Dedicated scheduler, runs at 8 PM ET
- **PostgreSQL**: Shared database

**Deployment Modes** (via `RUN_MODE` env var):
- `api-only`: API without scheduler (default for API service)
- `scheduler`: Pipeline worker only (default for pipeline worker)
- `combined`: Legacy mode, both in one container

### Basic Docker Commands

```bash
# View logs
docker-compose logs -f api
docker-compose logs -f pipeline-worker

# Check status
docker-compose ps

# Stop services
docker-compose down
```

For advanced deployment options (Kubernetes, scaling, monitoring), see [DEPLOYMENT.md](DEPLOYMENT.md).

---

## 🔧 Configuration

Key environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | postgresql+asyncpg://... | PostgreSQL connection string |
| `RUN_MODE` | combined | Deployment mode: `api-only`, `scheduler`, or `combined` |
| `PIPELINE_SCHEDULE_HOUR` | 20 | Hour to run pipeline (24h format) |
| `PIPELINE_TIMEZONE` | America/New_York | Timezone for scheduling |
| `PIPELINE_MAX_CONCURRENCY` | 5 | Max concurrent workers |
| `DEFAULT_MAX_SYMBOLS_PER_USER` | 50 | Max watchlist size |
| `TRADERCAT_AI_TOKEN` | - | GitHub Copilot SDK token |
| `LOG_FORMAT` | json | Log format (json or text) |

---

## 📊 Database Schema

### Core Tables
- **users**: User accounts with role-based access
- **api_keys**: SHA-256 hashed API keys
- **watchlist_items**: Per-user symbol tracking
- **signal_records**: Generated trading signals (GLOBAL/USER scope)
- **reports**: LLM-generated analysis reports
- **strategy_configs**: User-level strategy parameter overrides
- **pipeline_runs**: Pipeline execution tracking

---

## 🤝 Contributing

We welcome contributions! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Submit a pull request

---

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **OpenBB**: Market data integration
- **FastAPI**: Modern Python web framework
- **SQLAlchemy**: Database ORM
- **APScheduler**: Task scheduling
- **exchange_calendars**: Market holiday detection

---

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/AimeSoleil/TraderCat/issues)
- **Discussions**: [GitHub Discussions](https://github.com/AimeSoleil/TraderCat/discussions)

---

**Built with ❤️ by the TraderCat Team**
