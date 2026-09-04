# ProfitLens

ProfitLens is an evidence-grounded advertising profit root-cause investigation agent. It combines deterministic financial calculations with a bounded LangGraph workflow and an optional DeepSeek planner/report writer.

## Run the Phase 2 agent locally

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
make install
make agent-demo
```

`make agent-demo` uses the checked-in synthetic fixture and the deterministic fake model. It does not need a database or API key. The JSON output contains the detected incident, attribution, hypotheses, Evidence IDs, workflow events, and Chinese report. Replay files are written under `backend/artifacts/<incident_id>/<run_id>/`.

The original calculation-only command remains available:

```bash
make demo
```

## Start the API

```bash
make dev
```

Open `http://127.0.0.1:8000/docs` for the interactive API documentation. The fixture API exposes:

- `GET /api/incidents`
- `POST /api/detections/run`
- `GET /api/incidents/{incident_id}`
- `POST /api/incidents/{incident_id}/investigations`
- `GET /api/investigations/{run_id}/events`
- `GET /api/investigations/{run_id}/report`
- `POST /api/investigations/{run_id}/questions`

The investigation starts in a background worker. The events endpoint streams LangGraph
progress while the run is active and replays the same append-only JSONL events afterward.

## Use DeepSeek

Copy `.env.example` to `.env` and configure a newly generated key:

```dotenv
DATA_MODE=fixture
MODEL_MODE=deepseek
DEEPSEEK_API_KEY=replace-with-a-new-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

Validate the model connection with a harmless fixed prompt:

```bash
make model-check
```

Run an investigation with DeepSeek:

```bash
cd backend
uv run profitlens agent ../fixtures/demo/pricing_error.json --model deepseek
```

The API key is read as a Pydantic `SecretStr` and is never included in prompts, logs, artifacts, reports, or errors. If the model is unavailable or returns invalid JSON twice, ProfitLens finishes with deterministic planning and a template report marked `generated_without_llm`.

## Run natural-language analysis against MySQL

Provision MySQL users with `SELECT` permission only, then place the connection settings in the
ignored root `.env`. Replace every bracketed value locally; do not commit the resulting file.

```dotenv
DATA_MODE=readonly_db
MYSQL_STAT_URL=[DB20 read-only SQLAlchemy DSN ending in /au_stat]
MYSQL_CONFIG_URL=[DB40 read-only SQLAlchemy DSN ending in /ymgw]
STAT_TIMEZONE=UTC
CLI_TIMEZONE=Asia/Shanghai
MODEL_MODE=deepseek
DEEPSEEK_API_KEY=[your-key]
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

Check both connections with fixed `SELECT 1` queries, then ask a question:

```bash
make db-check
make ask QUESTION='分析昨天 offer 12345 为什么利润下降'
cd backend && uv run profitlens ask '分析最近3天美国利润下降原因' --json
uv run profitlens db-check
uv run profitlens chat
```

For follow-up questions, run `make chat`. Enter a first analysis question, ask follow-ups against
its report, use `/new` to clear the current investigation, and `/exit` to leave. Supported time
ranges include today, yesterday, recent N days, and ISO dates; one request is limited to seven
days. Input dates use `CLI_TIMEZONE`, while naive DB timestamps use `STAT_TIMEZONE`.

DB20 `au_stat.stat.cov` is the conversion count. `cov_aff` is channel-settled conversion data,
not advertiser approval data. The DDL does not provide complete price audit history, so a payout
or revenue rate change inferred from aggregates is corroborating metric evidence (`LIKELY`) unless
a real audit record is available.

Common failures are reported without URLs or credentials. Authentication/network errors require
checking access from the production network; “no analyzable data” means the requested period lacks
enough current data or four comparable historical slots.

## Database safety

Fixture mode is the default. Database infrastructure is optional and strictly read-only:

- The application has no database write, DDL, raw execute, or migration API.
- Queries are fixed `QuerySpec` objects with bound values, table/column allowlists, a 10-second timeout, and a maximum of 10,000 rows.
- sqlglot validates the AST again immediately before each driver call.
- ClickHouse requests set `readonly=2`; MySQL requires an externally provisioned account with only `SELECT` privileges.
- The LLM never receives SQL, credentials, connections, or raw performance rows.

MySQL mappings are fixed to the reviewed ADN DB20 `au_stat.stat` and DB40 `ymgw` tables. The
fixture demo remains the safe offline path when production networking is unavailable.

## Quality checks

```bash
make test
make check
```

The test suite covers deterministic RCA, bounded LangGraph execution, model fallback and Evidence-ID validation, local replay, all HTTP/SSE paths, and rejection of prohibited database statements.

## Architecture

```text
FastAPI / CLI
      |
InvestigationService
      |
Bounded LangGraph ---- DeepSeek or deterministic fallback
      |
Deterministic RCA core
      |
FixtureRepository or guarded read-only adapters
```

Financial metrics, loss attribution, confidence rules, and evidence are always produced by deterministic code. DeepSeek may only prioritize offered hypotheses and explain existing evidence.
