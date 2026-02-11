# Swagger UI Integration Guide

## Overview

TraderCat API now includes comprehensive Swagger UI integration with enhanced documentation, interactive testing capabilities, and automatic API key authentication support.

## Accessing the Documentation

Once the API server is running, you can access the documentation at:

- **Swagger UI (Interactive)**: http://localhost:8000/docs
- **ReDoc (Alternative View)**: http://localhost:8000/redoc
- **OpenAPI Schema (JSON)**: http://localhost:8000/openapi.json
- **API Root**: http://localhost:8000/

## Features

### 1. Enhanced API Metadata
- **Comprehensive description** with markdown formatting
- **Contact information** for support
- **License information** (MIT)
- **Version tracking** (2.0.0)

### 2. Organized API Groups
The API is organized into 7 logical groups:

| Tag | Description |
|-----|-------------|
| **users** | User management operations (Admin only) |
| **watchlist** | Manage user watchlist symbols |
| **strategies** | View and configure trading strategies |
| **signals** | Query trading signals (global + user) |
| **reports** | Access LLM-generated market analysis |
| **admin-pipeline** | Pipeline management (Admin only) |
| **admin-system** | System health and information |

### 3. API Key Authentication
- Automatic security scheme configuration
- `X-API-Key` header authentication
- "Authorize" button in Swagger UI for easy testing
- Persistent authorization (stored in browser)

### 4. Enhanced Swagger UI Options
- **Filter**: Search endpoints by keyword
- **Syntax Highlighting**: Monokai theme for code blocks
- **Request Duration**: Display how long each request takes
- **Try It Out**: Test endpoints directly from the UI
- **Collapsible Models**: View/hide model schemas
- **Persistent Auth**: API key saved across browser sessions

### 5. Server Configuration
Two preconfigured server URLs:
- Local development: `http://localhost:8000`
- Production placeholder: `https://api.tradercat.example.com`

## Using Swagger UI

### Step 1: Start the API Server

```bash
# Using uvicorn directly
RUN_MODE=api-only uvicorn tradercat.main:app --host 0.0.0.0 --port 8000

# Or using Docker Compose
docker-compose up -d api
```

### Step 2: Open Swagger UI

Navigate to: http://localhost:8000/docs

### Step 3: Authenticate

1. Click the **"Authorize"** button (top right with lock icon)
2. Enter your API key in the format: `tc_your_api_key_here`
3. Click **"Authorize"**
4. Close the dialog

Your API key will be automatically included in all requests.

### Step 4: Test Endpoints

1. **Expand an endpoint** by clicking on it
2. Click **"Try it out"** button
3. **Fill in parameters** (if required)
4. Click **"Execute"**
5. **View the response** below (status code, headers, body)

## Screenshots

### Swagger UI Main Interface
When you navigate to `/docs`, you'll see:
- Complete API documentation
- All 13 endpoints organized by tags
- Interactive "Try it out" functionality
- API key authorization button
- Request/response examples
- Model schemas

### Key Features Shown:
- **Header**: API title, version, description
- **Authorization**: Secure button for API key entry
- **Endpoint Groups**: Collapsible sections by tag
- **Method Badges**: GET (blue), POST (green), PUT (orange), DELETE (red)
- **Response Models**: Auto-generated from Pydantic models
- **Try It Out**: Direct API testing from browser

## OpenAPI Schema Details

The OpenAPI schema includes:

### Security Scheme
```yaml
components:
  securitySchemes:
    ApiKeyAuth:
      type: apiKey
      in: header
      name: X-API-Key
      description: API Key authentication. Get your key from admin.
```

### Endpoint Tags
All endpoints are organized with tags for better navigation:
- Users endpoints → `users` tag
- Watchlist endpoints → `watchlist` tag
- Strategy endpoints → `strategies` tag
- etc.

## Testing the Integration

### Verify Configuration

```bash
python << 'EOF'
import os
os.environ['RUN_MODE'] = 'api-only'
os.environ['DATABASE_URL'] = 'postgresql+asyncpg://test:test@localhost/test'

from tradercat.main import app

# Verify setup
assert app.title == "TraderCat API"
assert app.docs_url == "/docs"
assert app.redoc_url == "/redoc"
assert len(app.openapi_tags) == 7
print("✅ Swagger UI configuration verified!")
EOF
```

### Test OpenAPI Schema Generation

```bash
curl http://localhost:8000/openapi.json | python -m json.tool | head -50
```

## Troubleshooting

### Swagger UI Not Loading

1. **Check API server is running**:
   ```bash
   curl http://localhost:8000/
   ```

2. **Verify docs URL**:
   ```bash
   curl http://localhost:8000/docs
   ```

### Authentication Not Working

1. **Verify API key format**: Must start with `tc_`
2. **Check header name**: Must be exactly `X-API-Key`
3. **Test with curl**:
   ```bash
   curl -H "X-API-Key: tc_your_key" http://localhost:8000/api/v1/watchlist
   ```

## What's Included

✅ Interactive API documentation at `/docs`
✅ Alternative documentation at `/redoc`
✅ OpenAPI schema at `/openapi.json`
✅ API key authentication in Swagger UI
✅ Organized endpoint grouping (7 tags)
✅ Enhanced descriptions and metadata
✅ Syntax highlighting (Monokai theme)
✅ Request duration tracking
✅ Persistent authorization
✅ Filter/search functionality

**Ready for production!** 🚀
