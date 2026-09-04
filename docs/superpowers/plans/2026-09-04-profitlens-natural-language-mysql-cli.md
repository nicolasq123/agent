# ProfitLens Natural-Language MySQL CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user ask a Chinese profit question in `profitlens ask` or `profitlens chat`, safely load bounded read-only data from ADN's DB20/DB40 MySQL sources, and return an evidence-backed RCA report.

**Architecture:** DeepSeek converts natural language only into a strict `AnalysisIntent`; a deterministic fallback handles explicit common phrases. Source-controlled `QuerySpec` objects retrieve a bounded snapshot from separate DB20 and DB40 read-only connections, after which the existing deterministic RCA and bounded LangGraph workflow run without database awareness. The LLM never receives SQL, credentials, schema internals, or raw rows.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy async + asyncmy, sqlglot, LangGraph, OpenAI-compatible DeepSeek client, pytest, Ruff, strict Pyright.

**Spec:** `docs/superpowers/specs/2026-09-04-profitlens-natural-language-mysql-cli-design.md`

## Global Constraints

- Database access is MySQL-only in this release, with independent DB20 and DB40 URLs that may be identical.
- Both database accounts are externally provisioned with `SELECT` only; the application creates no users, schemas, tables, views, or migrations.
- LLM output may contain only a typed analysis intent or prose report; it never creates or executes SQL.
- Every SQL statement is a source-controlled, parameter-bound `QuerySpec`, revalidated immediately before execution.
- Reject writes, DDL, multi-statements, wildcards, locking reads, exports, and remote/file functions.
- Limit every run to 20 queries, every query to 10 seconds, and every result to 10,000 rows.
- Default CLI timezone is `Asia/Shanghai`; source timestamps use configurable `STAT_TIMEZONE`, default `UTC`.
- Missing time means the previous complete calendar day; missing scope triggers bounded scope discovery.
- Existing fixture commands, offline tests, HTTP APIs, and deterministic fallback behavior remain compatible.
- Secrets never appear in prompts, output, logs, exceptions, artifacts, or Git-tracked files.

---

### Task 1: Analysis Intent Contracts and Read-Only Configuration

**Files:**
- Create: `backend/src/ad_rca/agent/intent.py`
- Modify: `backend/src/ad_rca/agent/contracts.py`
- Modify: `backend/src/ad_rca/config.py`
- Modify: `.env.example`
- Test: `backend/tests/agent/test_intent.py`
- Test: `backend/tests/agent/test_contracts.py`

**Interfaces:**
- Consumes: existing `StrictModel`, `SliceKey`, `TimeWindow`, and `JsonCompletionClient` conventions.
- Produces: `AnalysisKind`, `AnalysisIntent`, `IntentParser.parse(question: str) -> AnalysisIntent`, and validated DB settings.

- [x] **Step 1: Write failing contract and configuration tests**

```python
def test_analysis_intent_is_frozen_and_rejects_unknown_fields() -> None:
    intent = AnalysisIntent(
        question="分析昨天 offer 12345 为什么利润下降",
        kind=AnalysisKind.PROFIT_RCA,
        window=TimeWindow(start=START, end=END),
        scope=SliceKey(offer_id="12345"),
        timezone="Asia/Shanghai",
    )
    assert intent.scope.offer_id == "12345"
    with pytest.raises(ValidationError):
        AnalysisIntent.model_validate({**intent.model_dump(), "sql": "SELECT 1"})


def test_readonly_db_requires_both_mysql_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_MODE", "readonly_db")
    monkeypatch.delenv("MYSQL_STAT_URL", raising=False)
    monkeypatch.delenv("MYSQL_CONFIG_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings()
```

- [x] **Step 2: Run the focused tests and verify missing-contract failures**

Run: `cd backend && uv run pytest tests/agent/test_intent.py tests/agent/test_contracts.py -q`

Expected: FAIL because `AnalysisIntent` and the MySQL settings do not exist.

- [x] **Step 3: Implement strict intent types and parser protocol**

```python
class AnalysisKind(StrEnum):
    PROFIT_RCA = "profit_rca"


class AnalysisIntent(StrictModel):
    question: str = Field(min_length=1, max_length=1000)
    kind: AnalysisKind = AnalysisKind.PROFIT_RCA
    window: TimeWindow
    scope: SliceKey = SliceKey()
    timezone: str = "Asia/Shanghai"


class IntentParser(Protocol):
    def parse(self, question: str) -> AnalysisIntent:
        raise NotImplementedError
```

- [x] **Step 4: Add secret-safe DB and timezone settings**

```python
mysql_stat_url: SecretStr | None = None
mysql_config_url: SecretStr | None = None
stat_timezone: str = "UTC"
cli_timezone: str = "Asia/Shanghai"

@model_validator(mode="after")
def require_readonly_db_urls(self) -> Self:
    if self.data_mode == "readonly_db" and (
        self.mysql_stat_url is None or self.mysql_config_url is None
    ):
        raise ValueError("MYSQL_STAT_URL and MYSQL_CONFIG_URL are required")
    ZoneInfo(self.stat_timezone)
    ZoneInfo(self.cli_timezone)
    return self
```

Keep `.env.example` values blank and document `mysql+asyncmy://` without a real host or credential.

- [x] **Step 5: Run focused tests and static checking**

Run: `cd backend && uv run pytest tests/agent/test_intent.py tests/agent/test_contracts.py -q && uv run pyright`

Expected: PASS with no type errors.

- [x] **Step 6: Commit the contracts**

```bash
git add .env.example backend/src/ad_rca/agent backend/src/ad_rca/config.py backend/tests/agent
git commit -m "feat: define natural language analysis intent"
```

---

### Task 2: DeepSeek Intent Parsing with Deterministic Fallback

**Files:**
- Create: `backend/src/ad_rca/infrastructure/models/intent.py`
- Modify: `backend/src/ad_rca/infrastructure/models/fake.py`
- Test: `backend/tests/infrastructure/models/test_intent.py`

**Interfaces:**
- Consumes: `AnalysisIntent`, `AnalysisKind`, `JsonCompletionClient`.
- Produces: `RuleIntentParser`, `DeepSeekIntentParser`, and `IntentParseError`.

- [x] **Step 1: Write failing tests for dates, scopes, isolation, repair, and fallback**

```python
NOW = datetime(2026, 9, 4, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_rule_parser_defaults_to_previous_complete_day() -> None:
    intent = RuleIntentParser(now=lambda: NOW).parse("分析 offer 12345 为什么利润下降")
    assert intent.window.start.isoformat() == "2026-09-03T00:00:00+08:00"
    assert intent.window.end.isoformat() == "2026-09-04T00:00:00+08:00"
    assert intent.scope == SliceKey(offer_id="12345")


def test_rule_parser_supports_channel_country_and_recent_days() -> None:
    intent = RuleIntentParser(now=lambda: NOW).parse("分析最近3天渠道678在美国的利润")
    assert intent.scope == SliceKey(channel_id="678", country="US")
    assert intent.window.start.isoformat() == "2026-09-01T00:00:00+08:00"


def test_deepseek_prompt_contains_no_sql_schema_or_secret() -> None:
    client = RecordingJsonClient(valid_intent_json())
    DeepSeekIntentParser(client, now=lambda: NOW).parse("分析昨天利润")
    prompt = " ".join(client.requests[0])
    assert "SELECT" not in prompt
    assert "au_stat" not in prompt
    assert "MYSQL_" not in prompt
```

Also assert one repair attempt for malformed JSON, rejection of a future/over-seven-day range,
and fallback to the rule parser on model unavailability.

- [x] **Step 2: Run the focused test and confirm adapter failures**

Run: `cd backend && uv run pytest tests/infrastructure/models/test_intent.py -q`

Expected: FAIL because intent parsers are missing.

- [x] **Step 3: Implement deterministic parsing**

Support `昨天`, `今天`, `最近N天`, ISO dates, `offer|oid`, `渠道|aid`, `广告主|ader`,
two-letter countries, and the initial `美国 -> US` alias. Anchor all relative dates with an
injected aware `now()` and `ZoneInfo(cli_timezone)`. Reject an empty question, end-before-start,
future windows, and ranges over seven days. Seven days keeps six candidates across eight
same-slot history weeks below the 10,000-row result ceiling.

```python
class RuleIntentParser:
    def __init__(self, *, timezone: str, now: Callable[[], datetime]) -> None:
        self._timezone = ZoneInfo(timezone)
        self._now = now
```

Its `parse(question: str) -> AnalysisIntent` method applies the exact supported phrase and
validation rules above and constructs the frozen contract directly.

- [x] **Step 4: Implement bounded DeepSeek parsing**

Ask for JSON matching a private strict `IntentDraft` containing only `start`, `end`, and the
four allowed dimensions. Include the injected current timestamp and default rules in the
system prompt. Validate the draft, perform one correction request on invalid output, and call
`RuleIntentParser` on `ModelUnavailableError` or repeated invalid output.

- [x] **Step 5: Run model tests and verify prompt isolation**

Run: `cd backend && uv run pytest tests/infrastructure/models/test_intent.py tests/infrastructure/models/test_deepseek.py -q && uv run pyright`

Expected: PASS; recorded prompts contain no SQL, table names, URLs, or secrets.

- [x] **Step 6: Commit parsers**

```bash
git add backend/src/ad_rca/infrastructure/models backend/tests/infrastructure/models
git commit -m "feat: parse bounded profit analysis intents"
```

---

### Task 3: Explicit Analysis Windows and Metric-Derived Price Evidence

**Files:**
- Modify: `backend/src/ad_rca/domain/models.py`
- Modify: `backend/src/ad_rca/detection/detector.py`
- Modify: `backend/src/ad_rca/application/core_service.py`
- Modify: `backend/src/ad_rca/rca/candidates.py`
- Modify: `backend/src/ad_rca/rca/verifiers/pricing.py`
- Test: `backend/tests/application/test_core_service.py`
- Test: `backend/tests/rca/verifiers/test_verifiers.py`

**Interfaces:**
- Consumes: `AnalysisIntent.window`, `AnalysisIntent.scope`, existing fixture repository.
- Produces: optional `analysis_window` and `base_scope` constructor arguments on
  `CoreRcaService`, scoped incidents, and honest
  metric-derived price evidence when configuration history is unavailable.

- [x] **Step 1: Write failing tests for a full requested window and incident scope**

```python
def test_core_uses_explicit_window_and_scope() -> None:
    service = CoreRcaService(
        repository,
        default_verifiers(),
        analysis_window=TimeWindow(start=DAY_START, end=DAY_END),
        base_scope=SliceKey(offer_id="12345"),
    )
    prepared = service.prepare(repository.scenario_id)
    assert prepared.incident is not None
    assert prepared.incident.window.start >= DAY_START
    assert prepared.incident.window.end <= DAY_END
    assert prepared.incident.scope == SliceKey(offer_id="12345")
```

Retain a regression test proving omitted `analysis_window` still selects the last three hours.

- [x] **Step 2: Run the focused test and verify the constructor rejects new arguments**

Run: `cd backend && uv run pytest tests/application/test_core_service.py -q`

Expected: FAIL with unexpected constructor arguments.

- [x] **Step 3: Implement explicit window/scope without changing fixture defaults**

Filter current rows using the explicit half-open window. Set `DetectionConfig.window_count` to
the expected hour count and pass `base_scope` into `detect_incident`. Build expected rows for
each current hour from the median of the eight matching weekday/hour historical slots, rather
than multiplying a single undifferentiated median.

Add `scope: SliceKey | None = None` as the final keyword argument to `detect_incident` and set
the constructed incident's scope to `scope if scope is not None else SliceKey()`. Do not change
any other incident field or default call site.

- [x] **Step 4: Write failing tests for measured payout/revenue rate shifts**

```python
def test_pricing_verifier_marks_measured_rate_increase_as_likely() -> None:
    context = context_with_rates(
        current_payout=900,
        current_conversions=300,
        baseline_payout=600,
        baseline_conversions=300,
        config_changes=(),
    )
    result = PricingVerifier().verify(context)
    assert result.status == HypothesisStatus.SUPPORTED
    assert result.confidence == Confidence.LIKELY
    assert result.evidence[0].source.dataset == "performance"
```

- [x] **Step 5: Implement measured-rate candidates without fabricating config history**

When direct `ConfigChange` evidence exists, preserve current confirmed behavior. Otherwise,
compare effective payout/conversion and revenue/conversion against baseline, require a material
20% adverse shift, emit corroborating `performance` evidence, and cap confidence at `LIKELY`.
Use only existing aggregate values; do not create fake old configuration records.

- [x] **Step 6: Run core, detection, RCA, and regression tests**

Run: `cd backend && uv run pytest tests/application/test_core_service.py tests/detection tests/rca -q && uv run pyright`

Expected: PASS including all Phase 1 scenarios.

- [x] **Step 7: Commit the core extension**

```bash
git add backend/src/ad_rca/domain backend/src/ad_rca/detection backend/src/ad_rca/application/core_service.py backend/src/ad_rca/rca backend/tests/application backend/tests/detection backend/tests/rca
git commit -m "feat: analyze explicit profit windows and measured rates"
```

---

### Task 4: Fixed ADN MySQL Query Catalog and Connectivity Checks

**Files:**
- Create: `backend/src/ad_rca/infrastructure/database/mysql_catalog.py`
- Modify: `backend/src/ad_rca/infrastructure/database/mysql.py`
- Test: `backend/tests/infrastructure/database/test_mysql_catalog.py`
- Test: `backend/tests/infrastructure/database/test_readonly_executors.py`

**Interfaces:**
- Consumes: `QuerySpec`, `ReadonlyMySqlExecutor`.
- Produces: `stat_query_specs()`, `config_query_specs()`, and
  `ReadonlyMySqlExecutor.check() -> None`.

- [x] **Step 1: Write failing catalog tests**

```python
def test_catalog_contains_only_fixed_bounded_selects() -> None:
    specs = {**stat_query_specs(), **config_query_specs()}
    assert {
        "health",
        "performance_scoped",
        "scope_candidates_by_advertiser",
        "scope_candidates_by_offer",
        "scope_candidates_by_channel",
        "scope_candidates_by_country",
        "performance_by_advertiser",
        "performance_by_offer",
        "performance_by_channel",
        "performance_by_country",
        "settlement",
        "margin",
        "cap_observations",
        "routing_changes",
    } <= set(specs)
    assert all(spec.dialect == "mysql" for spec in specs.values())
    assert all("LIMIT" in spec.sql.upper() for spec in specs.values())
```

Also instantiate every spec so sqlglot validates all table and column allowlists, and assert
that no SQL string contains a wildcard or a prohibited statement node.

- [x] **Step 2: Run tests and verify the catalog is missing**

Run: `cd backend && uv run pytest tests/infrastructure/database/test_mysql_catalog.py -q`

Expected: FAIL because `mysql_catalog` does not exist.

- [x] **Step 3: Implement literal performance query specs**

`performance_scoped` selects and aggregates these exact columns from `au_stat.stat`:
`dt`, `ader_id`, `oid_`, `aid`, `country`, `clk_os`, `carrier`, `clk`, `cov`, `cov_aff`,
`revenue`, and `payout`. It filters `history_start <= dt < window_end` and applies optional
bound advertiser/offer/channel/country predicates. It groups by hour and the four RCA
dimensions, orders deterministically, and ends in `LIMIT 10000`.

Create two literal queries for each dimension. `scope_candidates_by_*` aggregates the bounded
history/current interval, orders by total business volume, and returns at most six concrete
values. `performance_by_*` accepts exactly six bound candidate values (padding unused numeric
slots with `-1` and country slots with `__none__`), then groups their current and eight-week
same-slot history by hour and dimension. With a maximum seven-day requested window, this is at
most 9,072 rows. Do not interpolate a dimension supplied by a user or model.

- [x] **Step 4: Implement DB40 evidence specs**

Use fixed, parameterized selects over:

```text
ymgw.settlement: id, oid, aid, payout, ratio, status, inactive, ut
ymgw.margin: id, ader_id, oid, aid, ratio2, margin_type, status, inactive, ut
ymgw.cap + cap_log + remain_cap: cap id/value, usage, hit interval and reason
ymgw.redirect: id, ader_id, oid, aid, toid, inactive, ut
```

Filter by the selected scope and relevant time where a timestamp exists. `health` is exactly
`SELECT 1 AS ok LIMIT 1`. All result limits are literals at or below 10,000.

- [x] **Step 5: Add a guarded health method**

```python
async def check(self) -> None:
    rows = await self.query("health", {})
    if not rows or rows[0].get("ok") != 1:
        raise RuntimeError("MySQL read check returned an invalid result")
```

This method must not expose the engine, DSN, or generic execution.

- [x] **Step 6: Run database tests and static checks**

Run: `cd backend && uv run pytest tests/infrastructure/database -q && uv run ruff check . && uv run pyright`

Expected: PASS; existing prohibited-query tests remain green.

- [x] **Step 7: Commit the catalog**

```bash
git add backend/src/ad_rca/infrastructure/database backend/tests/infrastructure/database
git commit -m "feat: add fixed ADN MySQL query catalog"
```

---

### Task 5: Bounded MySQL Scope Discovery and Snapshot Loading

**Files:**
- Create: `backend/src/ad_rca/data/mysql_snapshot.py`
- Create: `backend/src/ad_rca/application/scope_discovery.py`
- Modify: `backend/src/ad_rca/domain/models.py`
- Test: `backend/tests/data/test_mysql_snapshot.py`
- Test: `backend/tests/application/test_scope_discovery.py`

**Interfaces:**
- Consumes: `AnalysisIntent`, two async named-query readers, fixed catalog row shapes.
- Produces: `LoadedAnalysisSnapshot`, `discover_scope(intent, rows_by_dimension) ->
  ScopeDiscovery`, and a populated
  `FixtureRepository` compatible with the existing core.

- [x] **Step 1: Write failing deterministic scope-ranking tests**

```python
def test_discovery_selects_the_largest_loss_dimension() -> None:
    result = discover_scope(
        intent=unscoped_yesterday_intent(),
        rows_by_dimension={
            "offer_id": performance_series("12345", loss=900),
            "channel_id": performance_series("678", loss=300),
            "advertiser_id": (),
            "country": (),
        },
    )
    assert result.selected_scope == SliceKey(offer_id="12345")
    assert result.lost_profit == 900
```

Tie-break in the stable order advertiser, country, channel, offer only after comparing loss;
ignore candidates with fewer than four comparable historical slots.

- [x] **Step 2: Write failing loader tests with recording readers**

```python
@pytest.mark.anyio
async def test_loader_uses_user_scope_without_discovery() -> None:
    loader = MySqlSnapshotLoader(stat_reader, config_reader, stat_timezone="UTC")
    snapshot = await loader.load(intent_with_offer("12345"))
    assert [call.name for call in stat_reader.calls] == ["performance_scoped"]
    assert snapshot.selected_scope == SliceKey(offer_id="12345")
    assert snapshot.repository.all_performance()
```

For an unscoped intent, assert four candidate reads and four time-series reads followed by one
scoped performance read and only relevant DB40 evidence reads. Assert all parameters equal
validated intent values and the complete run stays below the 20-query budget.

- [x] **Step 3: Run tests and verify missing loader/discovery failures**

Run: `cd backend && uv run pytest tests/application/test_scope_discovery.py tests/data/test_mysql_snapshot.py -q`

Expected: FAIL because modules do not exist.

- [x] **Step 4: Implement typed DB evidence models**

Add frozen `SettlementObservation` and `MarginObservation` contracts with record ID, observed
time, relevant IDs, and numeric settings. Extend `ScenarioBundle` with optional tuples for
these records. Keep fixture JSON backward compatible through empty defaults.

- [x] **Step 5: Implement deterministic scope discovery**

Map each discovery result to timezone-aware aggregate `PerformanceRow` values with sentinel
IDs only for dimensions absent from that fixed query. For each concrete dimension value,
compare current-window profit to median matching weekday/hour history and rank positive loss.
Return a typed `ScopeDiscovery` containing requested scope, selected scope, loss, and source
dimension. Raise `NoAnalyzableDataError` when no candidate has enough data.

- [x] **Step 6: Implement snapshot loading and row validation**

```python
@dataclass(frozen=True)
class LoadedAnalysisSnapshot:
    intent: AnalysisIntent
    selected_scope: SliceKey
    repository: FixtureRepository


class MySqlSnapshotLoader:
    async def check(self) -> None:
        await self._stat_reader.check()
        await self._config_reader.check()
```

Implement `load(self, intent: AnalysisIntent) -> LoadedAnalysisSnapshot` with the exact
discovery, history, mapping, and evidence-query sequence defined in Steps 5 and 6.

Use `history_start = intent.window.start - timedelta(weeks=8)`. Localize naive `dt`/`ut`
values using `STAT_TIMEZONE`, convert them to the intent timezone, and reject malformed rows.
Map `cov` to conversions and retain `cov_aff` in a new optional `settled_conversions` field;
do not claim it is advertiser approval. Query DB40 only after selecting a bounded scope.

- [x] **Step 7: Run loader, domain, fixture, and static tests**

Run: `cd backend && uv run pytest tests/data tests/application/test_scope_discovery.py tests/domain -q && uv run pyright`

Expected: PASS, including old fixture documents without new evidence fields.

- [x] **Step 8: Commit snapshot loading**

```bash
git add backend/src/ad_rca/data backend/src/ad_rca/application/scope_discovery.py backend/src/ad_rca/domain/models.py backend/tests/data backend/tests/application/test_scope_discovery.py backend/tests/domain
git commit -m "feat: load bounded RCA snapshots from MySQL"
```

---

### Task 6: Natural-Language Investigation Service

**Files:**
- Create: `backend/src/ad_rca/application/natural_language_service.py`
- Modify: `backend/src/ad_rca/api/dependencies.py`
- Modify: `backend/src/ad_rca/application/investigation_service.py`
- Test: `backend/tests/application/test_natural_language_service.py`

**Interfaces:**
- Consumes: `IntentParser`, `MySqlSnapshotLoader`, `InvestigationPlanner`, `ReportComposer`,
  `ArtifactStore`.
- Produces: `NaturalLanguageAnalysisService.ask`, `.answer`, `.check_database`, and
  `build_natural_language_service(settings)`.

- [ ] **Step 1: Write a failing end-to-end service test with fake boundaries**

```python
@pytest.mark.anyio
async def test_question_runs_real_workflow_over_loaded_snapshot(tmp_path: Path) -> None:
    service = NaturalLanguageAnalysisService(
        parser=FixedIntentParser(pricing_intent()),
        loader=FakeSnapshotLoader(pricing_snapshot()),
        planner=FakePlanner(),
        composer=TemplateReportComposer(),
        artifact_store=ArtifactStore(tmp_path),
        id_factory=lambda: "run-natural-language",
    )
    analysis = await service.ask("分析昨天 offer 12345 为什么利润下降")
    assert analysis.run.result.status == RunStatus.COMPLETED
    assert analysis.run.report.conclusions
    assert analysis.intent.scope.offer_id == "12345"
```

Add tests for no incident, no data, database failure, deterministic model fallback, DB checks,
and a follow-up answer that may cite only Evidence IDs from the current report.

- [ ] **Step 2: Run the focused tests and verify service absence**

Run: `cd backend && uv run pytest tests/application/test_natural_language_service.py -q`

Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement analysis sessions and orchestration**

```python
@dataclass(frozen=True)
class NaturalLanguageAnalysis:
    intent: AnalysisIntent
    selected_scope: SliceKey
    run: WorkflowRun


class NaturalLanguageAnalysisService:
    async def check_database(self) -> None:
        await self._loader.check()
```

Implement `ask(self, question: str) -> NaturalLanguageAnalysis` and
`answer(self, analysis: NaturalLanguageAnalysis, question: str) -> QuestionAnswer` with the
orchestration and Evidence-ID rules immediately below.

`ask` parses, loads, constructs `CoreRcaService` with the explicit window/scope, and runs the
existing `InvestigationWorkflow`. Preserve artifact persistence and deterministic model/report
fallback. Extract the existing Evidence-ID validation into one shared helper instead of
duplicating or weakening it.

- [ ] **Step 4: Implement dependency construction**

`build_natural_language_service(settings)` must require `DATA_MODE=readonly_db`, unwrap DB URLs
only at driver construction, build separate stat/config executors with their respective fixed
catalogs and one shared 20-query `QueryBudget`, and choose DeepSeek or deterministic adapters.
The existing `build_service` fixture path remains unchanged.

- [ ] **Step 5: Run application and workflow tests**

Run: `cd backend && uv run pytest tests/application tests/workflow -q && uv run pyright`

Expected: PASS with fixture service regressions green.

- [ ] **Step 6: Commit the service**

```bash
git add backend/src/ad_rca/application backend/src/ad_rca/api/dependencies.py backend/tests/application
git commit -m "feat: orchestrate natural language MySQL investigations"
```

---

### Task 7: `ask`, `chat`, and `db-check` CLI Commands

**Files:**
- Create: `backend/src/ad_rca/presentation/__init__.py`
- Create: `backend/src/ad_rca/presentation/markdown.py`
- Modify: `backend/src/ad_rca/cli.py`
- Test: `backend/tests/presentation/test_markdown.py`
- Test: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `NaturalLanguageAnalysisService` and typed analysis/report models.
- Produces: `profitlens ask`, `profitlens chat`, `profitlens db-check`, Markdown output, and
  injectable input/output boundaries for deterministic CLI tests.

- [ ] **Step 1: Write failing one-shot CLI tests**

```python
def test_ask_prints_markdown_report(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["ask", "分析昨天 offer 12345 为什么利润下降"],
        natural_service_factory=lambda settings: fake_natural_service(),
    )
    output = capsys.readouterr()
    assert code == 0
    assert "利润损失" in output.out
    assert "Evidence" in output.out


def test_ask_json_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["ask", "分析昨天利润", "--json"],
        natural_service_factory=lambda settings: fake_natural_service(),
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["run"]["report"]
```

- [ ] **Step 2: Write failing REPL and DB-check tests**

Inject a line reader returning the sequence `分析昨天利润`, `还有哪些证据？`, `/new`, `/exit`.
Assert the first line calls `ask`, the second calls `answer` on that session, `/new` clears it,
and `/exit` performs no query. Assert `db-check` invokes both readers and prints only source
names and `ok`, never DSNs or secrets.

- [ ] **Step 3: Run CLI tests and verify missing subcommands**

Run: `cd backend && uv run pytest tests/test_cli.py tests/presentation/test_markdown.py -q`

Expected: FAIL because the subcommands and renderer are missing.

- [ ] **Step 4: Implement concise Markdown rendering**

Render requested and selected scope, period, actual/expected/lost profit, ranked conclusions,
confidence, Evidence IDs, and recommendations. Render insufficient evidence and no-incident
results explicitly. Never render configuration objects or raw database rows.

- [ ] **Step 5: Implement async-compatible CLI entry points**

Add parsers:

```text
profitlens ask QUESTION [--json]
profitlens chat
profitlens db-check
```

Use `asyncio.run` only at CLI boundaries. `chat` prints a short prompt, treats `/new` and
`/exit` locally, requires an investigation before a follow-up, and catches EOF/interrupt
without a traceback. Preserve all current commands and their output.

- [ ] **Step 6: Sanitize CLI failures**

Map missing settings, intent ambiguity, no data, authentication, timeout, and budget errors to
short messages and exit code 2. Extend `_safe_error` by exception type; never interpolate DSNs,
driver exception strings containing URLs, or request parameters.

- [ ] **Step 7: Run all CLI/presentation tests and static checks**

Run: `cd backend && uv run pytest tests/test_cli.py tests/presentation -q && uv run ruff check . && uv run pyright`

Expected: PASS, including old `investigate`, `agent`, `serve`, and `model-check` tests.

- [ ] **Step 8: Commit CLI commands**

```bash
git add backend/src/ad_rca/cli.py backend/src/ad_rca/presentation backend/tests/test_cli.py backend/tests/presentation
git commit -m "feat: add natural language RCA CLI"
```

---

### Task 8: Make Commands, Contributor Guide, and Operator Documentation

**Files:**
- Modify: `Makefile`
- Create: `AGENTS.md` only if it still does not exist
- Modify: `README.md`
- Test: `backend/tests/test_documented_commands.py`

**Interfaces:**
- Consumes: completed CLI commands and current repository tooling.
- Produces: discoverable local commands and repository-specific contribution guidance.

- [ ] **Step 1: Recheck the root before creating `AGENTS.md`**

Run: `test ! -e AGENTS.md`

Expected: exit 0. If the file exists, do not overwrite or modify it; omit it from this task.

- [ ] **Step 2: Write failing documentation-command tests**

```python
def test_makefile_documents_every_public_target() -> None:
    makefile = ROOT.joinpath("Makefile").read_text()
    for target in ("install", "test", "check", "demo", "agent-demo", "model-check", "dev", "ask", "chat", "db-check"):
        assert f"# {target}:" in makefile
```

Also assert README examples reference real argparse subcommands and never contain a populated
secret or a database mutation statement.

- [ ] **Step 3: Add actionable comments and targets to Makefile**

Place a Chinese comment immediately above every existing and new target using the form
`# target: purpose; usage`. Add:

```makefile
ask:
	cd backend && uv run profitlens ask "$(QUESTION)"

chat:
	cd backend && uv run profitlens chat

db-check:
	cd backend && uv run profitlens db-check
```

Document `make ask QUESTION='分析昨天利润为什么下降'`; do not embed credentials.

- [ ] **Step 4: Create the concise contributor guide if absent**

Write a 200–400 word `AGENTS.md` titled `Repository Guidelines`. Cover project layout, every
Make command, Python 3.12/Ruff/100-column/strict-Pyright conventions, pytest naming and
coverage, commit prefixes observed in history (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`),
PR evidence, ignored `.env`, local artifacts, and the absolute prohibition on DB writes.

- [ ] **Step 5: Update README operator instructions**

Document safe DB20/DB40 URL configuration, `make db-check`, one-shot usage, REPL commands,
timezone defaults, JSON output, source limitations, and troubleshooting. State explicitly that
`cov_aff` is channel-settled conversion data and that price-history conclusions are metric
corroboration unless a real audit source exists.

- [ ] **Step 6: Run documentation tests and command help**

Run: `cd backend && uv run pytest tests/test_documented_commands.py -q && uv run profitlens --help && uv run profitlens ask --help`

Expected: PASS; help lists `ask`, `chat`, and `db-check`.

- [ ] **Step 7: Commit documentation**

```bash
git add Makefile README.md backend/tests/test_documented_commands.py
test ! -e AGENTS.md || git add AGENTS.md
git commit -m "docs: explain natural language database workflows"
```

---

### Task 9: Security and End-to-End Acceptance

**Files:**
- Create: `backend/tests/test_natural_language_acceptance.py`
- Modify: `docs/superpowers/plans/2026-09-04-profitlens-natural-language-mysql-cli.md`

**Interfaces:**
- Consumes: the completed contracts, parsers, catalogs, loader, service, and CLI.
- Produces: reproducible evidence that the user-facing goal and read-only invariants hold.

- [ ] **Step 1: Write the failing acceptance test**

Drive `main(["ask", "分析昨天 offer 12345 为什么利润下降", "--json"])` through the real
rule parser, real query catalog, recording async DB20/DB40 clients, real deterministic core,
real LangGraph workflow, and fake planner/composer. Assert:

```python
assert payload["intent"]["scope"]["offer_id"] == "12345"
assert payload["run"]["report"]["conclusions"]
assert payload["run"]["result"]["evidence"]
assert all(call.sql.lstrip().upper().startswith("SELECT") for call in db_calls)
assert len(db_calls) <= 20
assert secret not in json.dumps(payload)
```

Add a second unscoped question proving scope discovery selects the fixture's largest-loss
offer before investigation, and a scripted `chat` test proving cited follow-up answers.

- [ ] **Step 2: Run acceptance and observe any integration gaps**

Run: `cd backend && uv run pytest tests/test_natural_language_acceptance.py -q`

Expected before final integration fixes: FAIL only at concrete wiring mismatches exposed by the
end-to-end path, not because tests bypass missing components.

- [ ] **Step 3: Fix only the observed integration gaps**

Keep boundaries unchanged: intent remains typed, query names remain fixed, DB clients remain
read-only, and the LLM remains unable to provide SQL. Add focused regression assertions for
each wiring correction before changing implementation.

- [ ] **Step 4: Search tracked source for forbidden capabilities and secrets**

Run:

```bash
git grep -n -E '(^|[^A-Za-z])(INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP|TRUNCATE|RENAME|MERGE|GRANT|REVOKE)([^A-Za-z]|$)' -- backend/src || true
git grep -n -E 'sk-[A-Za-z0-9]{12,}|mysql\+asyncmy://[^:@/]+:[^@/]+@' -- . ':!docs/superpowers/specs/2026-09-04-profitlens-natural-language-mysql-cli-design.md' || true
git check-ignore .env
```

Expected: no executable database mutation in `backend/src`, no tracked real-looking secret,
and `.env` reported as ignored. Review any match manually rather than accepting the grep alone.

- [ ] **Step 5: Run the complete verification suite**

Run: `make test && make check && make agent-demo && make model-check`

Expected: all tests pass, coverage does not fall below the current 93%, Ruff formatting/checks
pass, strict Pyright reports zero errors, the offline demo completes, and the configured
DeepSeek probe returns status `ok`.

- [ ] **Step 6: Run safe live DB acceptance when URLs are explicitly configured**

Run:

```bash
make db-check
make ask QUESTION='分析昨天整体利润为什么下降'
```

Expected: both MySQL sources report `ok`; the analysis either returns a cited RCA, reports no
incident, or reports insufficient data without exposing DSNs or issuing a write. If the current
machine cannot reach production, leave this gate unchecked and provide these exact commands
for execution in the production network.

- [ ] **Step 7: Mark the plan only from observed evidence and commit**

Check each completed box only after its command succeeds. Do not mark the live DB gate when it
was simulated. Then run:

```bash
git add backend/tests/test_natural_language_acceptance.py docs/superpowers/plans/2026-09-04-profitlens-natural-language-mysql-cli.md
git commit -m "test: verify natural language MySQL RCA workflow"
```

- [ ] **Step 8: Push the verified branch**

Run: `git status --short && git log --oneline --decorate -12 && git push origin HEAD`

Expected: clean working tree and successful push without force.
