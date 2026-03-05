# TraderCat Web

Next.js 16 frontend for the TraderCat trading-signal & report-generation platform.  
Built with **React 19**, **shadcn/ui**, **Tailwind CSS v4**, and **TanStack React Query**.

## Prerequisites

| Tool | Version |
|------|---------|
| Node.js | ≥ 22 |
| pnpm | ≥ 10 |

## Getting Started (Development)

```bash
# Install dependencies
pnpm install

# Start the dev server (http://localhost:3000)
pnpm dev
```

> The frontend expects the API at `http://localhost:8000` by default.  
> Override with `NEXT_PUBLIC_API_URL` in a `.env.local` file or via environment.

## Production Build (Local)

```bash
pnpm build   # outputs to .next/
pnpm start   # serves at http://localhost:3000
```

## Docker

A multi-stage Dockerfile is provided that uses Next.js **standalone** output for a minimal image.

### Build & run standalone

```bash
# From the web/ directory
docker build -t tradercat-web .
docker run -p 3000:3000 -e HOSTNAME=0.0.0.0 tradercat-web
```

### Override the API URL at build time

```bash
docker build --build-arg NEXT_PUBLIC_API_URL=https://api.example.com -t tradercat-web .
```

### Full stack via Docker Compose

From the project root:

```bash
docker compose up -d          # postgres + api + pipeline + web
docker compose up -d api web  # api + web only (skip pipeline)
```

| Service | URL |
|---------|-----|
| Web | http://localhost:3000 |
| API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API base URL (baked at build time) |

## Project Structure

```
web/
├── public/              # Static assets
├── src/
│   ├── app/             # Next.js App Router pages
│   │   ├── (admin)/     # Admin-only pages (pipeline, users, strategies …)
│   │   ├── (portal)/    # User pages (dashboard, signals, reports …)
│   │   └── login/       # Auth page
│   ├── components/      # React components + shadcn/ui primitives
│   ├── hooks/           # Custom React hooks
│   └── lib/             # API client, types, utilities
├── Dockerfile           # Multi-stage production build
├── next.config.ts       # Next.js configuration (standalone output)
├── package.json
└── tsconfig.json
```

## Tech Stack

- **Framework**: Next.js 16 (App Router, Turbopack)
- **UI**: shadcn/ui (new-york) + Tailwind CSS v4
- **State**: TanStack React Query v5
- **Auth**: PAT → JWT, cookie + localStorage guard
- **Markdown**: react-markdown + remark-gfm + rehype-highlight
