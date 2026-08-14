# Data Airlock Suite

Monorepo: Next.js UI in `apps/web`, FastAPI engine in `services/engine`, Postgres schema in `supabase/migrations`.

## Local commands

- Engine: `cd services/engine && python3 -m uvicorn app.main:app --reload --port 8000`
- Web: `cd apps/web && npm run dev`
- Engine tests: `cd services/engine && python3 -m pytest`
- Web tests: `cd apps/web && npm test`
- Root schema tests: `python3 -m pytest test_airlock.py`

## Cursor Cloud specific instructions

This environment is named **routes_hemali** and is connected to `github.com/poconnell10/data_airlock`.

Install (run during Builds) installs Python deps with `pip --user` and web deps with `npm ci --prefix apps/web`. Do not start the engine or Next.js from `install`.

On agent start, terminals launch:

- `engine` from `services/engine` on port 8000
- `web` from `apps/web` on port 3000

The engine starts without Supabase; persistence endpoints return a not-configured response until secrets are set. Optional environment secrets for a full stack: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Map the public values into `apps/web/.env.local` when running the UI against a real project.

Smoke checks after boot:

- `curl -fsS http://127.0.0.1:8000/health`
- Open `http://localhost:3000/properties/setup`
