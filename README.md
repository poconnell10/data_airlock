# Data Airlock Suite

Pre-transformation data ingestion control plane and property setup interface.

## Monorepo layout

| Path | Role |
|------|------|
| `apps/web` | Next.js 14 App Router — property setup UI |
| `services/engine` | FastAPI engine — inspect + Gate 1–4 dry-run |
| `supabase/migrations` | Postgres schema (contracts, properties, run reports) |

## Quick start

### Engine (local)

```bash
cd services/engine
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Web (local)

```bash
cd apps/web
cp .env.example .env.local
npm install
npm run dev
```

Open [http://localhost:3000/properties/setup](http://localhost:3000/properties/setup).

### Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

- Web: `http://localhost:3000`
- Engine: `http://localhost:8000/health`
- OpenAPI: `http://localhost:8000/docs`

### Database

```bash
supabase db reset   # applies supabase/migrations/*
```

## Deploy

- **Engine** → Railway via root `railway.json` (Dockerfile at `services/engine/Dockerfile`)
- **DB / Auth** → Supabase
- **Object storage** → S3-compatible (AWS S3 or Cloudflare R2)

## API surface

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness |
| `POST` | `/api/v1/inference/inspect` | Infer encoding, delimiter, sample headers (multipart file) |
| `POST` | `/api/v1/airlock/dry-run` | Simulate Gates 1–4; returns Run Report JSON |
