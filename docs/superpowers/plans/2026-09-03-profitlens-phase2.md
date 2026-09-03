# ProfitLens Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the deterministic Phase 1 RCA engine into a bounded LangGraph agent with DeepSeek-compatible model calls, HTTP/SSE APIs, replayable local artifacts, and strictly read-only database adapters.

**Architecture:** Keep all financial computation and evidence creation in the existing deterministic core. Add an application-level investigation preparation API, then orchestrate allowed hypothesis selection and report composition through a single bounded `StateGraph`; model implementations are dependency-injected and always have deterministic fallbacks. HTTP endpoints operate on fixture-backed repositories by default, persist only local artifacts, and database infrastructure exposes semantic read methods backed by AST-validated fixed queries.

**Tech Stack:** Python 3.12, Pydantic v2, LangGraph, FastAPI, OpenAI Python SDK, pydantic-settings, sqlglot, SQLAlchemy 2/asyncmy, clickhouse-connect, pytest/httpx.

**Spec:** `docs/superpowers/specs/2026-09-02-profitlens-design.md`

## Global Constraints

- Database interaction is strictly read-only; no write, DDL, locking read, file export, URL, remote-table, or multi-statement query is accepted.
- LLMs never generate SQL, calculate financial metrics, create evidence, create root-cause types, or access credentials/raw records.
- The workflow performs at most two investigation rounds, at most three verifiers per round, and at most twenty data queries per run.
- Every reported root-cause conclusion references an Evidence ID produced by deterministic code.
- Fixture and Fake-LLM modes require neither a database nor an API key and remain deterministic.
- Model failure or invalid output retries validation once and then degrades to deterministic planning/reporting.
- `domain`, `detection`, and `rca` must not import LangGraph, FastAPI, model SDKs, or database drivers.

---

### Task 1: Configuration, agent contracts, and report models

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/src/ad_rca/config.py`
- Create: `backend/src/ad_rca/agent/__init__.py`
- Create: `backend/src/ad_rca/agent/contracts.py`
- Create: `backend/src/ad_rca/agent/models.py`
- Create: `backend/tests/agent/test_contracts.py`
- Create: `.env.example`

**Interfaces:**
- Consumes: existing `HypothesisType`, `CoreInvestigationResult`, and `Evidence` models.
- Produces: `Settings`, `InvestigationPlanner`, `ReportComposer`, `InvestigationPlan`, `InvestigationReport`, `ReportConclusion`, and deterministic fallback implementations.

- [x] **Step 1: Write failing tests for settings and immutable structured contracts**

```python
def test_settings_default_to_fixture_and_fake_model(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.data_mode == "fixture"
    assert settings.model_mode == "fake"
    assert settings.deepseek_model == "deepseek-v4-flash"

def test_plan_rejects_more_than_three_hypotheses():
    with pytest.raises(ValidationError):
        InvestigationPlan(hypotheses=list(HypothesisType)[:4], rationale="too many")
```

- [x] **Step 2: Run `uv run pytest tests/agent/test_contracts.py -q` and verify missing-module failure**
- [x] **Step 3: Add dependencies and implement strict settings/contracts/models with `extra="forbid"`**
- [x] **Step 4: Add `.env.example` with blank secret and explicit fake/fixture defaults**
- [x] **Step 5: Run the focused tests and `uv run pyright`**
- [x] **Step 6: Commit `feat: define phase two agent contracts`**

### Task 2: Prepare deterministic investigations for controlled orchestration

**Files:**
- Modify: `backend/src/ad_rca/application/core_service.py`
- Create: `backend/src/ad_rca/application/investigation_case.py`
- Create: `backend/tests/application/test_investigation_case.py`
- Modify: `backend/tests/application/test_core_service.py`

**Interfaces:**
- Consumes: `FixtureRepository`, `DetectionConfig`, existing attribution/decomposition/candidate/verifier functions.
- Produces: `PreparedInvestigation`, `CoreRcaService.prepare(scenario_id)`, and `CoreRcaService.verify(prepared, selected)`; existing `investigate` remains backward compatible.

- [x] **Step 1: Write a failing test that prepares candidates without verifying them**

```python
prepared = service.prepare("pricing")
assert prepared.incident is not None
assert prepared.candidates[0] is HypothesisType.PAYOUT_PRICE_INCREASE
assert prepared.context.incident == prepared.incident
```

- [x] **Step 2: Run the focused test and verify `prepare` is absent**
- [x] **Step 3: Extract the current deterministic stages into an immutable `PreparedInvestigation`**
- [x] **Step 4: Write a failing test that rejects unoffered and duplicate verifier selections**
- [x] **Step 5: Implement `verify`, evidence guards, and backward-compatible `investigate` composition**
- [x] **Step 6: Run application and Phase 1 regression tests**
- [x] **Step 7: Commit `refactor: expose controlled RCA investigation stages`**

### Task 3: Fake and DeepSeek-compatible model adapters

**Files:**
- Create: `backend/src/ad_rca/infrastructure/__init__.py`
- Create: `backend/src/ad_rca/infrastructure/models/__init__.py`
- Create: `backend/src/ad_rca/infrastructure/models/fake.py`
- Create: `backend/src/ad_rca/infrastructure/models/deepseek.py`
- Create: `backend/tests/infrastructure/models/test_fake.py`
- Create: `backend/tests/infrastructure/models/test_deepseek.py`

**Interfaces:**
- Consumes: contracts from Task 1 and only redacted aggregate summaries.
- Produces: `FakePlanner`, `TemplateReportComposer`, `DeepSeekPlanner`, `DeepSeekReportComposer`, and `ModelUnavailableError`.

- [x] **Step 1: Write failing deterministic fake-planner/composer tests, including Evidence-ID citation checks**
- [x] **Step 2: Run the tests and verify missing adapter failures**
- [x] **Step 3: Implement deterministic adapters that select offered candidates and render a Chinese template report**
- [x] **Step 4: Write failing DeepSeek adapter tests using an injected fake chat client response; assert prompts contain no SQL, credentials, or raw rows**
- [x] **Step 5: Implement OpenAI-compatible Chat Completions calls against configured base URL, strict JSON parsing, one repair call, timeout, and secret-safe exceptions**
- [x] **Step 6: Run adapter tests and static checks**
- [x] **Step 7: Commit `feat: add fake and DeepSeek model adapters`**

### Task 4: Bounded LangGraph workflow and local run artifacts

**Files:**
- Create: `backend/src/ad_rca/workflow/__init__.py`
- Create: `backend/src/ad_rca/workflow/state.py`
- Create: `backend/src/ad_rca/workflow/events.py`
- Create: `backend/src/ad_rca/workflow/graph.py`
- Create: `backend/src/ad_rca/infrastructure/artifacts.py`
- Create: `backend/tests/workflow/test_graph.py`
- Create: `backend/tests/infrastructure/test_artifacts.py`

**Interfaces:**
- Consumes: prepared investigation service, planner/composer contracts, `InMemorySaver`.
- Produces: `InvestigationWorkflow.run(...) -> InvestigationReport`, ordered `WorkflowEvent` records, and `ArtifactStore` replay methods.

- [x] **Step 1: Write a failing graph test asserting ordered prepare/plan/verify/guard/report events and maximum two rounds**
- [x] **Step 2: Verify the graph test fails because workflow modules are missing**
- [x] **Step 3: Implement typed state, reducers, explicit nodes/edges, query/round/verifier budgets, and in-memory checkpoint compilation**
- [x] **Step 4: Write failing tests for planner/composer failure and invalid Evidence IDs**
- [x] **Step 5: Implement deterministic fallback with `generated_without_llm=true` and warning codes**
- [x] **Step 6: Write failing artifact tests for atomic JSON files and append-only `events.jsonl` replay**
- [x] **Step 7: Implement local artifact paths under `artifacts/<incident_id>/<run_id>/` with no database persistence**
- [x] **Step 8: Run workflow/artifact tests and static checks**
- [x] **Step 9: Commit `feat: orchestrate bounded investigations with LangGraph`**

### Task 5: SQL AST guard and read-only database executors

**Files:**
- Create: `backend/src/ad_rca/infrastructure/database/__init__.py`
- Create: `backend/src/ad_rca/infrastructure/database/sql_guard.py`
- Create: `backend/src/ad_rca/infrastructure/database/query_specs.py`
- Create: `backend/src/ad_rca/infrastructure/database/clickhouse.py`
- Create: `backend/src/ad_rca/infrastructure/database/mysql.py`
- Create: `backend/tests/infrastructure/database/test_sql_guard.py`
- Create: `backend/tests/infrastructure/database/test_readonly_executors.py`

**Interfaces:**
- Consumes: fixed `QuerySpec` values and bound parameters only.
- Produces: `validate_readonly_sql(sql, dialect)`, `ReadonlyClickHouseExecutor.query(spec, params)`, and `ReadonlyMySqlExecutor.query(spec, params)`; neither executor exposes command/execute/raw connection methods.

- [x] **Step 1: Write parameterized failing tests rejecting every forbidden statement from spec section 9.2, comments/CTEs that hide writes, multi-statements, locking reads, exports, URL/remote functions, and non-whitelisted tables**
- [x] **Step 2: Run and verify missing guard failure**
- [x] **Step 3: Implement sqlglot single-statement AST validation, SELECT/UNION-only roots, recursive forbidden-node/function checks, and table/column allowlists**
- [x] **Step 4: Write failing executor tests with fake driver clients asserting only validated fixed query specs and bounded limits/timeouts are sent**
- [x] **Step 5: Implement ClickHouse query-only adapter with readonly settings and MySQL SQLAlchemy async query-only adapter that relies on an externally provisioned SELECT-only account**
- [x] **Step 6: Assert source contains no public write method and run a repository-wide forbidden-SQL test**
- [x] **Step 7: Run database tests and static checks**
- [x] **Step 8: Commit `feat: enforce read-only database access`**

### Task 6: Investigation application service and run registry

**Files:**
- Create: `backend/src/ad_rca/application/investigation_service.py`
- Create: `backend/src/ad_rca/application/run_registry.py`
- Create: `backend/tests/application/test_investigation_service.py`
- Create: `backend/tests/application/test_run_registry.py`

**Interfaces:**
- Consumes: fixture catalog, workflow factory, artifact store.
- Produces: `list_incidents`, `detect`, `start_investigation`, `get_events`, `get_report`, and `answer_question`; POST operations mutate only in-memory state/local artifacts.

- [x] **Step 1: Write failing tests that list three fixture incidents and complete all three through the workflow**
- [x] **Step 2: Implement fixture catalog and synchronous bounded run lifecycle with stable UUIDs**
- [x] **Step 3: Write failing replay and incident-scoped question tests**
- [x] **Step 4: Implement artifact-backed replay and constrained questions that receive only the existing report/evidence summary**
- [x] **Step 5: Run application tests and static checks**
- [x] **Step 6: Commit `feat: add investigation application service`**

### Task 7: FastAPI and SSE surface

**Files:**
- Create: `backend/src/ad_rca/api/__init__.py`
- Create: `backend/src/ad_rca/api/schemas.py`
- Create: `backend/src/ad_rca/api/dependencies.py`
- Create: `backend/src/ad_rca/api/app.py`
- Create: `backend/tests/api/test_api.py`

**Interfaces:**
- Consumes: Task 6 application service.
- Produces: the seven `/api` endpoints from spec section 10.1, JSON errors, and SSE event replay with `text/event-stream`.

- [x] **Step 1: Write failing TestClient tests for incident listing/detail, detection, investigation creation, event streaming, report retrieval, and questions**
- [x] **Step 2: Verify missing API app failure**
- [x] **Step 3: Implement app factory and typed schemas without exposing configuration secrets**
- [x] **Step 4: Implement SSE using persisted event replay; add explicit 404/409/422 error behavior**
- [x] **Step 5: Add a test proving POST endpoints never call a database writer and only create local artifacts**
- [x] **Step 6: Run API integration tests and static checks**
- [x] **Step 7: Commit `feat: expose investigation HTTP and SSE APIs`**

### Task 8: CLI, developer commands, live-model probe, and Phase 2 acceptance

**Files:**
- Modify: `backend/src/ad_rca/cli.py`
- Modify: `Makefile`
- Create: `README.md`
- Create: `backend/tests/test_phase2_acceptance.py`
- Modify: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: settings, application service, API app, all three fixtures.
- Produces: `profitlens agent`, `profitlens serve`, `profitlens model-check`, `make agent-demo`, and `make dev` commands.

- [ ] **Step 1: Write failing CLI tests for fake-agent execution, model configuration check without printing secrets, and server factory selection**
- [ ] **Step 2: Implement commands; `model-check` sends only a fixed harmless prompt and `agent` defaults to fake mode**
- [ ] **Step 3: Write the failing Phase 2 acceptance test that runs all three fixtures through HTTP, validates ordered SSE events, replays reports, and confirms deterministic fallback**
- [ ] **Step 4: Implement Make targets and concise Phase 2 README usage/security documentation**
- [ ] **Step 5: Run `make test`, `make check`, and the three fixture workflows without a key**
- [ ] **Step 6: With an explicitly configured local key, run `profitlens model-check` and one live DeepSeek investigation without logging the key**
- [ ] **Step 7: Search the repository for forbidden SQL and accidentally tracked secrets; confirm `.env` stays ignored**
- [ ] **Step 8: Commit `feat: complete phase two agent backend`**

## Completion Gate

- [ ] All Phase 1 and Phase 2 tests pass.
- [ ] `make check` passes with strict Pyright and Ruff.
- [ ] Three fixture scenarios run through HTTP and emit replayable SSE events and reports.
- [ ] Fake-model and model-failure paths produce deterministic reports without API keys.
- [ ] A live `deepseek-v4-flash` probe succeeds when a valid key is configured.
- [ ] SQL guard tests reject every prohibited query category and adapters expose read-only APIs only.
- [ ] No secret appears in Git-tracked files, logs, exceptions, artifacts, prompts, or reports.
- [ ] `domain`, `detection`, and `rca` remain independent of Phase 2 frameworks.
