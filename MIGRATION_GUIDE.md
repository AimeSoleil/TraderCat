# Database Migration Guide

## Overview

TraderCat uses [Alembic](https://alembic.sqlalchemy.org/) for database migrations. This guide covers how to set up the database, run migrations, and seed the initial admin user.

## Prerequisites

- PostgreSQL 16+ installed and running
- Python 3.10+ with TraderCat dependencies installed
- Database credentials configured in `.env` file

## Quick Start

### 1. Configure Database

Copy the example environment file and update database credentials:

```bash
cp .env.example .env
```

Edit `.env` and set your database URL:

```bash
DATABASE_URL=postgresql+asyncpg://username:password@localhost:5432/tradercat
```

### 2. Run Migrations

Run all migrations to set up the database schema and seed the initial admin:

```bash
alembic upgrade head
```

**Output Example:**
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 001, Initial database schema
INFO  [alembic.runtime.migration] Running upgrade 001 -> 002, Seed initial admin user

================================================================================
🎉 INITIAL ADMIN USER CREATED SUCCESSFULLY!
================================================================================
Username: admin
Email:    admin@tradercat.local
Role:     admin
Max Symbols: 100

🔑 API KEY (save this, it won't be shown again):
   tc_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890
================================================================================

Use this API key in the X-API-Key header to authenticate API requests.
Example: curl -H 'X-API-Key: {key}' http://localhost:8000/api/v1/users
```

**⚠️ IMPORTANT**: Save the API key! It's only shown once and cannot be retrieved later.

## Customizing the Initial Admin

You can customize the initial admin user by setting environment variables **before** running migrations:

```bash
export ADMIN_USERNAME=myadmin
export ADMIN_EMAIL=admin@mycompany.com
export ADMIN_MAX_SYMBOLS=200

alembic upgrade head
```

Or add them to your `.env` file:

```bash
ADMIN_USERNAME=myadmin
ADMIN_EMAIL=admin@mycompany.com
ADMIN_MAX_SYMBOLS=200
```

## Migration Commands

### Check Current Version

```bash
alembic current
```

### View Migration History

```bash
alembic history
```

### Upgrade to Specific Version

```bash
alembic upgrade 002  # Upgrade to revision 002
```

### Downgrade

```bash
alembic downgrade -1  # Downgrade one revision
alembic downgrade 001 # Downgrade to specific revision
alembic downgrade base # Remove all migrations
```

**⚠️ Warning**: Downgrading will delete data!

### Create New Migration

If you need to create a new migration after modifying models:

```bash
alembic revision --autogenerate -m "Description of changes"
```

## Idempotency

The seed admin migration (002) is **idempotent** - it checks if an admin user already exists before creating one. This means:

- ✅ Safe to run multiple times
- ✅ Won't create duplicate admin users
- ✅ Can be used in CI/CD pipelines

If the admin user already exists, you'll see:

```
ℹ️  Admin user 'admin' already exists. Skipping seed.
```

## Docker Deployment

When using Docker Compose, migrations run automatically on container startup:

```bash
docker-compose up -d
```

The `api` service's entrypoint runs `alembic upgrade head` before starting the API server.

### Docker Environment Variables

Set admin credentials in `docker-compose.yml`:

```yaml
services:
  api:
    environment:
      - ADMIN_USERNAME=admin
      - ADMIN_EMAIL=admin@mycompany.com
      - ADMIN_MAX_SYMBOLS=100
```

Or use an `.env` file (recommended):

```bash
# .env
ADMIN_USERNAME=admin
ADMIN_EMAIL=admin@mycompany.com
ADMIN_MAX_SYMBOLS=100
```

## Troubleshooting

### Migration Already Exists

If you see an error about an existing admin user when running migrations:

```
ℹ️  Admin user 'admin' already exists. Skipping seed.
```

This is **normal** - the migration detected an existing admin and skipped creation.

### Database Connection Error

If you get a connection error:

```
sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) could not connect to server
```

**Solutions**:
1. Check PostgreSQL is running: `systemctl status postgresql`
2. Verify database credentials in `.env`
3. Ensure database exists: `createdb tradercat`
4. Check firewall/network settings

### Permission Denied

If you get a permission error:

```
sqlalchemy.exc.ProgrammingError: (psycopg2.ProgrammingError) permission denied for schema public
```

**Solution**: Grant necessary permissions:

```sql
GRANT ALL PRIVILEGES ON DATABASE tradercat TO your_user;
GRANT ALL ON SCHEMA public TO your_user;
```

### Lost API Key

If you lost the admin API key:

**Option 1**: Create a new API key via database:

```sql
-- Connect to database
psql -d tradercat

-- Generate new key hash (replace 'your_new_key' with actual key)
-- Key should be like: tc_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890

INSERT INTO api_keys (id, user_id, key_hash, key_prefix, name, is_active, created_at)
SELECT 
  gen_random_uuid(),
  id,
  encode(digest('your_plaintext_key_here', 'sha256'), 'hex'),
  'tc_AbCdEfGh',
  'Recovery Key',
  true,
  NOW()
FROM users WHERE username = 'admin';
```

**Option 2**: Reset database and re-run migrations:

```bash
# ⚠️ WARNING: This deletes all data!
alembic downgrade base
alembic upgrade head
```

## Database Schema

The migrations create the following tables:

### Core Tables

1. **users** - User accounts
2. **api_keys** - API authentication keys
3. **watchlist_items** - User watchlist symbols
4. **strategy_configs** - User strategy parameter overrides

### Signal & Report Tables

5. **signal_records** - Generated trading signals
6. **reports** - LLM-generated analysis reports
7. **pipeline_runs** - Pipeline execution tracking

## Migration Files

| File | Description |
|------|-------------|
| `001_initial_schema.py` | Creates all database tables and indexes |
| `002_seed_admin_user.py` | Seeds initial admin user with API key |

## Next Steps

After running migrations:

1. **Save your API key** from the migration output
2. **Test authentication**:
   ```bash
   curl -H "X-API-Key: your_api_key" http://localhost:8000/api/admin/system/health
   ```
3. **Access Swagger UI**: http://localhost:8000/docs
4. **Create additional users** via `/api/v1/users` endpoint

## Security Best Practices

1. **Never commit** API keys to version control
2. **Rotate keys regularly** by creating new ones and deleting old ones
3. **Use strong, unique keys** (automatically generated by the system)
4. **Store keys securely** (password managers, secret management tools)
5. **Monitor API key usage** via `last_used_at` field
6. **Disable inactive keys** by setting `is_active = false`

## References

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [TraderCat API Documentation](http://localhost:8000/docs)
