# ProfitLens Deterministic RCA Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python package and CLI that read immutable advertising fixtures, detect profit incidents, attribute loss, verify supported causes, and emit an evidence-backed report without a database or LLM.

**Architecture:** Domain and RCA modules are pure Python with Pydantic contracts and Polars-backed calculations. A readonly fixture repository supplies current, historical, configuration, cap, postback, and quality observations; an application service composes the deterministic stages and a CLI serializes the result.

**Tech Stack:** Python 3.12, uv, Pydantic v2, Polars, NumPy, pytest, pytest-cov, Ruff, Pyright

**Spec:** `docs/superpowers/specs/2026-09-02-profitlens-design.md`

## Global Constraints

- Python version is exactly the spec floor: Python 3.12 or newer.
- Database interaction is absent from Phase 1; fixture readers expose read methods only.
- No SQL, model SDK, LangGraph, FastAPI, or frontend dependency is introduced in this phase.
- Primary dimensions are `advertiser_id`, `offer_id`, `channel_id`, and `country`; maximum attribution depth is 3.
- Maximum investigation rounds remain 2 and maximum verifiers per round remain 3 for interfaces that Phase 2 will consume.
- Core calculations never consume model-generated numbers or conclusions.
- All public Pydantic models reject unknown fields with `extra="forbid"`.
- Tests and the demo run without network access.

---

## File Map

```text
backend/
  pyproject.toml                       package metadata and tool configuration
  src/ad_rca/
    __init__.py                        public package version
    domain/enums.py                    stable enum vocabulary
    domain/models.py                   shared Pydantic contracts
    data/ports.py                      readonly repository protocols
    data/fixture_repository.py         immutable JSON fixture reader
    detection/metrics.py               aggregate and derived metrics
    detection/baseline.py              same-slot median and MAD baseline
    detection/quality.py               completeness and sample gates
    detection/detector.py              PROFIT_DROP and NEGATIVE_PROFIT detector
    rca/contribution.py                one-to-three dimension loss attribution
    rca/decomposition.py               volume, mix, and efficiency effects
    rca/candidates.py                  deterministic hypothesis candidates
    rca/verifiers/base.py              verifier protocol and context
    rca/verifiers/pricing.py           price-change evidence
    rca/verifiers/cap.py               cap evidence
    rca/verifiers/conversion.py        conversion-path evidence
    rca/verifiers/traffic_mix.py       traffic-mix evidence
    rca/verifiers/traffic_quality.py   traffic-quality evidence
    application/core_service.py        deterministic end-to-end use case
    evaluation/scorer.py               ground-truth score calculation
    cli.py                             fixture-mode command line entrypoint
  tests/                               unit, contract, integration, and CLI tests
fixtures/
  demo/*.json                          three immutable demo incidents
  ground_truth/*.json                  expected outcomes
```

## Task 1: Package Foundation and Domain Contracts

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/src/ad_rca/__init__.py`
- Create: `backend/src/ad_rca/domain/__init__.py`
- Create: `backend/src/ad_rca/domain/enums.py`
- Create: `backend/src/ad_rca/domain/models.py`
- Create: `backend/tests/domain/test_models.py`

**Interfaces:**
- Consumes: no earlier task.
- Produces: `TimeWindow`, `SliceKey`, `PerformanceRow`, `MetricSnapshot`, `BaselineResult`, `Incident`, `AttributionResult`, `Evidence`, `HypothesisResult`, and `CoreInvestigationResult`.

- [ ] **Step 1: Add the package configuration**

Create `backend/pyproject.toml` with a `src` layout, `requires-python = ">=3.12"`, runtime dependencies `pydantic>=2.11,<3`, `polars>=1.32,<2`, and `numpy>=2.2,<3`, plus development dependencies `pytest`, `pytest-cov`, `ruff`, and `pyright`. Register the CLI as `profitlens = "ad_rca.cli:main"`. Configure Ruff for Python 3.12 with line length 100 and Pyright in strict mode.

- [ ] **Step 2: Write failing domain model tests**

Create tests that prove timezone-naive windows and unknown fields are rejected and that derived properties are safe around zero:

```python
def test_time_window_requires_timezone() -> None:
    with pytest.raises(ValidationError):
        TimeWindow(start=datetime(2026, 9, 2, 10), end=datetime(2026, 9, 2, 11))


def test_metric_snapshot_handles_zero_denominators() -> None:
    snapshot = MetricSnapshot.from_totals(
        clicks=0, conversions=0, approved_conversions=0, revenue=0.0, payout=0.0
    )
    assert snapshot.profit == 0.0
    assert snapshot.margin is None
    assert snapshot.cvr is None
```

- [ ] **Step 3: Run the tests and confirm the expected failure**

Run: `cd backend && uv run pytest tests/domain/test_models.py -q`

Expected: collection fails because `ad_rca.domain.models` does not exist.

- [ ] **Step 4: Implement stable enums and Pydantic contracts**

Define string enums for `IncidentType`, `HypothesisType`, `HypothesisStatus`, `Confidence`, `EvidenceStrength`, and `RunStatus`. Define all models with a shared strict base:

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TimeWindow(StrictModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("time window must be timezone-aware")
        if self.start >= self.end:
            raise ValueError("start must be before end")
        return self
```

Use `float` for generated monetary calculations in V1 and round only at presentation boundaries. `SliceKey` has optional values for the four allowed dimensions and a `depth` property. `PerformanceRow` contains the eleven raw/derived inputs needed by later tasks. `Evidence` carries `evidence_id`, hypothesis, strength, source, statement, calculation, and `explained_loss`. `CoreInvestigationResult` aggregates the incident, attributions, hypotheses, evidence, contradictions, status, and residual loss.

- [ ] **Step 5: Run quality checks**

Run: `cd backend && uv run pytest tests/domain/test_models.py -q && uv run ruff check . && uv run pyright`

Expected: all commands pass.

- [ ] **Step 6: Commit the package foundation**

```bash
git add backend/pyproject.toml backend/src/ad_rca backend/tests/domain
git commit -m "feat: define ProfitLens domain contracts"
```

## Task 2: Readonly Fixture Repository

**Files:**
- Create: `backend/src/ad_rca/data/__init__.py`
- Create: `backend/src/ad_rca/data/ports.py`
- Create: `backend/src/ad_rca/data/fixture_repository.py`
- Create: `backend/tests/data/test_fixture_repository.py`
- Create: `backend/tests/fixtures/minimal_scenario.json`

**Interfaces:**
- Consumes: `TimeWindow`, `SliceKey`, and `PerformanceRow` from Task 1.
- Produces: `AnalyticsReader`, `OperationalReader`, `ScenarioBundle`, and `FixtureRepository.load(path: Path) -> FixtureRepository`.

- [ ] **Step 1: Write the repository contract tests**

Use a minimal JSON document with `metadata`, `performance`, `config_changes`, `caps`, `postbacks`, and `quality_events`. Test that loading validates all records, source lists are tuples, filtering cannot mutate the repository, and an unknown dimension raises `ValueError`.

```python
def test_repository_filters_known_dimensions(repository: FixtureRepository) -> None:
    rows = repository.performance(
        window=TimeWindow(start=START, end=END),
        slice_key=SliceKey(offer_id="offer-a"),
    )
    assert rows
    assert {row.offer_id for row in rows} == {"offer-a"}
```

- [ ] **Step 2: Run the tests and confirm the expected failure**

Run: `cd backend && uv run pytest tests/data/test_fixture_repository.py -q`

Expected: import fails because the data package does not exist.

- [ ] **Step 3: Define readonly protocols**

`AnalyticsReader` exposes only `performance`, `conversion_events`, `postback_events`, and `quality_events`. `OperationalReader` exposes only `pricing_changes`, `cap_observations`, and `routing_changes`. Every method returns immutable tuples. Do not define `execute`, mutation, schema, or connection accessors.

- [ ] **Step 4: Implement the JSON fixture reader**

Load bytes once, validate into `ScenarioBundle`, store the frozen Pydantic object, and filter in memory with an allowlisted attribute lookup:

```python
ALLOWED_DIMENSIONS = frozenset({"advertiser_id", "offer_id", "channel_id", "country"})


def _matches(row: PerformanceRow, key: SliceKey) -> bool:
    return all(value is None or getattr(row, name) == value for name, value in key.dimensions())
```

The fixture adapter must never write, normalize, or repair its source file.

- [ ] **Step 5: Run repository and static checks**

Run: `cd backend && uv run pytest tests/data/test_fixture_repository.py -q && uv run ruff check . && uv run pyright`

Expected: all commands pass.

- [ ] **Step 6: Commit the readonly fixture boundary**

```bash
git add backend/src/ad_rca/data backend/tests/data backend/tests/fixtures
git commit -m "feat: add immutable fixture repository"
```

## Task 3: Metrics, Baseline, and Data Quality

**Files:**
- Create: `backend/src/ad_rca/detection/__init__.py`
- Create: `backend/src/ad_rca/detection/metrics.py`
- Create: `backend/src/ad_rca/detection/baseline.py`
- Create: `backend/src/ad_rca/detection/quality.py`
- Create: `backend/tests/detection/test_metrics.py`
- Create: `backend/tests/detection/test_baseline.py`
- Create: `backend/tests/detection/test_quality.py`

**Interfaces:**
- Consumes: `PerformanceRow`, `MetricSnapshot`, `BaselineResult`, and `TimeWindow`.
- Produces: `aggregate_metrics(rows) -> MetricSnapshot`, `build_profit_baseline(current_hour, history) -> BaselineResult`, and `assess_data_quality(rows, expected_hours, minimum_clicks) -> DataQualityResult`.

- [ ] **Step 1: Write failing metric aggregation tests**

Test summed raw values and recomputed ratios. Ratios must be calculated from totals rather than averaged from row ratios.

```python
def test_aggregate_metrics_recomputes_cvr_from_totals() -> None:
    result = aggregate_metrics(rows_with_100_clicks_and_10_conversions())
    assert result.clicks == 100
    assert result.conversions == 10
    assert result.cvr == pytest.approx(0.1)
```

- [ ] **Step 2: Write failing robust baseline tests**

Cover eight same-slot observations with one extreme outlier, MAD zero, missing timezone, and fewer than four usable history points. The outlier must not materially change the median.

- [ ] **Step 3: Write failing data-quality tests**

Verify completeness below 95%, insufficient clicks, missing monetary values, and a valid complete window. Define `DataQualityStatus` as `PASS`, `INCOMPLETE`, or `INSUFFICIENT_SAMPLE`.

- [ ] **Step 4: Run tests and confirm failures**

Run: `cd backend && uv run pytest tests/detection -q`

Expected: imports fail for the unimplemented detection modules.

- [ ] **Step 5: Implement aggregation and baseline calculations**

Use Polars for aggregation and NumPy for median/MAD. Select history rows whose weekday and hour match the current slot. Require at least four usable values. Return an explicit `mad_zero` flag and use a configured absolute deviation floor rather than dividing by an arbitrary epsilon.

```python
def robust_z(actual: float, median: float, mad: float, deviation_floor: float) -> float:
    scale = max(mad, deviation_floor)
    return 0.6745 * (actual - median) / scale
```

- [ ] **Step 6: Implement data-quality assessment**

Completeness is observed distinct hours divided by expected hours. Reject incomplete windows before applying minimum sample checks. Return structured reasons used by the detector and future UI.

- [ ] **Step 7: Run all Task 3 checks**

Run: `cd backend && uv run pytest tests/detection -q && uv run ruff check . && uv run pyright`

Expected: all commands pass.

- [ ] **Step 8: Commit metrics and baseline support**

```bash
git add backend/src/ad_rca/detection backend/tests/detection
git commit -m "feat: add robust profit baseline calculations"
```

## Task 4: Deterministic Incident Detector

**Files:**
- Create: `backend/src/ad_rca/detection/detector.py`
- Create: `backend/tests/detection/test_detector.py`

**Interfaces:**
- Consumes: Task 3 aggregation, baseline, and quality functions.
- Produces: `DetectionConfig` and `detect_incident(current_windows, history, config) -> DetectionResult`.

- [ ] **Step 1: Write failing detector tests**

Cover a 2-of-3 profit drop, a single noisy hour, a normal scenario, a low-impact drop, a near-zero expected profit, a sustained negative-profit case, and data-quality blocking.

```python
def test_detects_two_of_three_profit_drop() -> None:
    result = detect_incident(current_drop_rows(), normal_history_rows(), DetectionConfig())
    assert result.incident is not None
    assert result.incident.incident_type is IncidentType.PROFIT_DROP
    assert result.incident.triggered_windows == 2
```

- [ ] **Step 2: Run the test and confirm failure**

Run: `cd backend && uv run pytest tests/detection/test_detector.py -q`

Expected: import fails for `detection.detector`.

- [ ] **Step 3: Implement the composite detector**

Default configuration uses `robust_z_threshold=-3.0`, `relative_drop_threshold=0.20`, `minimum_absolute_loss=500.0`, `required_hits=2`, `window_count=3`, and a configurable baseline profit floor. Evaluate only completed windows that pass quality checks. Return `DATA_QUALITY_BLOCKED` without an Incident when any required current window is incomplete.

- [ ] **Step 4: Run detector and regression tests**

Run: `cd backend && uv run pytest tests/detection -q && uv run ruff check . && uv run pyright`

Expected: all commands pass.

- [ ] **Step 5: Commit the incident detector**

```bash
git add backend/src/ad_rca/detection/detector.py backend/tests/detection/test_detector.py
git commit -m "feat: detect robust profit incidents"
```

## Task 5: Contribution Attribution and Effect Decomposition

**Files:**
- Create: `backend/src/ad_rca/rca/__init__.py`
- Create: `backend/src/ad_rca/rca/contribution.py`
- Create: `backend/src/ad_rca/rca/decomposition.py`
- Create: `backend/tests/rca/test_contribution.py`
- Create: `backend/tests/rca/test_decomposition.py`

**Interfaces:**
- Consumes: current and expected `PerformanceRow` sequences and the four allowlisted dimensions.
- Produces: `attribute_loss(actual, expected, dimensions, max_depth=3, min_share=0.10) -> AttributionSummary` and `decompose_profit_change(actual, expected) -> EffectDecomposition`.

- [ ] **Step 1: Write failing attribution tests**

Create a dataset where `offer-a/channel-c/US` explains 62% of loss. Verify the top path, descending ranking, maximum depth, minimum-share pruning, and explicit residual.

```python
def test_attributes_loss_to_expected_combination() -> None:
    summary = attribute_loss(actual_rows(), expected_rows(), ALLOWED_DIMENSIONS)
    assert summary.paths[0].slice_key == SliceKey(
        offer_id="offer-a", channel_id="channel-c", country="US"
    )
    assert summary.paths[0].share == pytest.approx(0.62, abs=0.02)
```

- [ ] **Step 2: Write failing decomposition tests**

Use controlled scenarios with only total traffic change, only distribution change, and only unit economics change. Verify volume, mix, and efficiency effects reconcile to total profit change within a documented tolerance.

- [ ] **Step 3: Run tests and confirm failures**

Run: `cd backend && uv run pytest tests/rca/test_contribution.py tests/rca/test_decomposition.py -q`

Expected: imports fail for the new RCA modules.

- [ ] **Step 4: Implement bounded combination attribution**

Generate dimension combinations for depths 1 through 3 from the allowlist. Aggregate actual and expected profit for each slice, retain positive loss contributors, prune below `min_share`, and remove redundant descendants that do not add explanatory value over their parent. Return residual as `total_loss - explained_loss`.

- [ ] **Step 5: Implement volume/mix/efficiency decomposition**

Use an additive counterfactual decomposition with baseline traffic shares and per-click profit. Document the calculation in model fields so Evidence can expose the exact inputs. Treat zero-click slices explicitly and include their impact in residual when no stable per-click baseline exists.

- [ ] **Step 6: Run all RCA checks**

Run: `cd backend && uv run pytest tests/rca -q && uv run ruff check . && uv run pyright`

Expected: all commands pass and contribution reconciliation errors stay within test tolerance.

- [ ] **Step 7: Commit attribution logic**

```bash
git add backend/src/ad_rca/rca backend/tests/rca
git commit -m "feat: attribute and decompose profit loss"
```

## Task 6: Candidate Generation and Five Verifiers

**Files:**
- Create: `backend/src/ad_rca/rca/candidates.py`
- Create: `backend/src/ad_rca/rca/verifiers/__init__.py`
- Create: `backend/src/ad_rca/rca/verifiers/base.py`
- Create: `backend/src/ad_rca/rca/verifiers/pricing.py`
- Create: `backend/src/ad_rca/rca/verifiers/cap.py`
- Create: `backend/src/ad_rca/rca/verifiers/conversion.py`
- Create: `backend/src/ad_rca/rca/verifiers/traffic_mix.py`
- Create: `backend/src/ad_rca/rca/verifiers/traffic_quality.py`
- Create: `backend/tests/rca/verifiers/test_verifiers.py`
- Create: `backend/tests/rca/test_candidates.py`

**Interfaces:**
- Consumes: `MetricSnapshot`, `AttributionSummary`, and readonly operational/analytics observations.
- Produces: `generate_candidates(context) -> tuple[HypothesisType, ...]`, `VerificationContext`, and `Verifier.verify(context) -> HypothesisResult`.

- [ ] **Step 1: Write failing candidate tests**

Verify deterministic mappings: increased payout per conversion proposes `PAYOUT_PRICE_INCREASE`; stable clicks plus changed offer shares proposes `TRAFFIC_MIX_SHIFT`; falling approval rate plus rising short CTIT proposes `TRAFFIC_QUALITY_DEGRADATION`. Candidate order must be stable and duplicates removed.

- [ ] **Step 2: Write parameterized verifier contract tests**

For each verifier, provide supported, contradicted, and missing-data contexts. Assert status, maximum confidence, Evidence IDs, contradiction preservation, and explained loss bounds.

```python
@pytest.mark.parametrize("verifier,context,expected", VERIFIER_CASES)
def test_verifier_contract(verifier: Verifier, context: VerificationContext, expected: HypothesisStatus) -> None:
    result = verifier.verify(context)
    assert result.status is expected
    assert all(item.hypothesis is result.hypothesis for item in result.evidence)
```

- [ ] **Step 3: Run tests and confirm failures**

Run: `cd backend && uv run pytest tests/rca/test_candidates.py tests/rca/verifiers -q`

Expected: imports fail for candidate and verifier modules.

- [ ] **Step 4: Implement the verifier protocol and evidence factory**

`VerificationContext` contains the incident, affected slice, current/baseline metrics, attribution, and immutable auxiliary observations. `Verifier` exposes only `hypothesis` and `verify`. Generate deterministic Evidence IDs from the hypothesis, slice, source record IDs, and calculation name using SHA-256 truncated to 16 hexadecimal characters.

- [ ] **Step 5: Implement pricing, cap, and conversion verifiers**

Pricing reaches `CONFIRMED` only when a temporally aligned price change exists and counterfactual recomputation explains at least 80% of the affected-slice loss. Cap reaches `CONFIRMED` only with a cap-hit observation and delivery change aligned to the incident. Conversion-path failure uses postback errors, latency, CVR, and approval changes; without a direct failure event its confidence cannot exceed `LIKELY`.

- [ ] **Step 6: Implement traffic-mix and traffic-quality verifiers**

Traffic mix compares baseline and actual shares and references Task 5 decomposition. Traffic quality combines duplicate-IP, short-CTIT, blacklist, and approval-rate signals; it cannot return `CONFIRMED` without an external adjudication record. Every verifier records contrary signals instead of dropping them.

- [ ] **Step 7: Run verifier and full backend checks**

Run: `cd backend && uv run pytest tests/rca -q && uv run ruff check . && uv run pyright`

Expected: all commands pass.

- [ ] **Step 8: Commit deterministic verification**

```bash
git add backend/src/ad_rca/rca backend/tests/rca
git commit -m "feat: verify bounded RCA hypotheses"
```

## Task 7: Deterministic Core Service

**Files:**
- Create: `backend/src/ad_rca/application/__init__.py`
- Create: `backend/src/ad_rca/application/core_service.py`
- Create: `backend/tests/application/test_core_service.py`

**Interfaces:**
- Consumes: `FixtureRepository`, detector, attribution, candidate generator, and verifier registry.
- Produces: `CoreRcaService.investigate(scenario_id: str) -> CoreInvestigationResult`.

- [ ] **Step 1: Write failing application tests**

Test a pricing incident end to end, a normal scenario with no Incident, a data-quality block, and a quality scenario that never exceeds `LIKELY`. Verify every conclusion Evidence ID exists in the result.

- [ ] **Step 2: Run the tests and confirm failure**

Run: `cd backend && uv run pytest tests/application/test_core_service.py -q`

Expected: import fails for `application.core_service`.

- [ ] **Step 3: Implement the deterministic pipeline**

Compose stages in this order: load scenario, assess quality, detect incident, attribute loss, decompose effects, generate candidates, select the first three candidates, run registered verifiers, apply confidence guards, and return the structured result. No natural-language report is generated in Phase 1.

```python
class CoreRcaService:
    def __init__(self, repository: FixtureRepository, verifiers: Mapping[HypothesisType, Verifier]): ...

    def investigate(self, scenario_id: str) -> CoreInvestigationResult: ...
```

- [ ] **Step 4: Enforce evidence guards**

Before returning, reject duplicate Evidence IDs, unknown citations, explained loss greater than affected loss beyond tolerance, `CONFIRMED` without direct Evidence, and quality-root-cause confidence above `LIKELY` without adjudication.

- [ ] **Step 5: Run application and regression tests**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run pyright`

Expected: all commands pass.

- [ ] **Step 6: Commit the core use case**

```bash
git add backend/src/ad_rca/application backend/tests/application
git commit -m "feat: compose deterministic RCA pipeline"
```

## Task 8: Demo Scenarios, Evaluation, and CLI

**Files:**
- Create: `fixtures/demo/pricing_error.json`
- Create: `fixtures/demo/cap_mix_shift.json`
- Create: `fixtures/demo/traffic_quality.json`
- Create: `fixtures/ground_truth/pricing_error.json`
- Create: `fixtures/ground_truth/cap_mix_shift.json`
- Create: `fixtures/ground_truth/traffic_quality.json`
- Create: `backend/src/ad_rca/evaluation/__init__.py`
- Create: `backend/src/ad_rca/evaluation/scorer.py`
- Create: `backend/src/ad_rca/cli.py`
- Create: `backend/tests/evaluation/test_scorer.py`
- Create: `backend/tests/test_cli.py`
- Create: `.gitignore`
- Create: `Makefile`

**Interfaces:**
- Consumes: `CoreRcaService` and `CoreInvestigationResult`.
- Produces: `score_result(result, ground_truth) -> ScenarioScore` and `profitlens investigate <fixture-path>`.

- [ ] **Step 1: Add three immutable demo scenarios and ground truth**

Encode the approved cases with timezone-aware timestamps and eight matching historical slots. Pricing error must contain a payout change 15 minutes before the incident and explain at least 80% of slice loss. Cap mix shift must preserve total clicks while moving traffic to a lower-margin Offer. Traffic quality must increase short CTIT and duplicate IP rates while reducing approval rate, with expected confidence `LIKELY`.

- [ ] **Step 2: Write failing scorer tests**

Verify incident type, expected slice, root-cause Top-1 and Top-3, confidence ceiling, explained-loss threshold, and Evidence citation coverage. A result that overstates `CONFIRMED` must fail even if the root-cause type matches.

- [ ] **Step 3: Write failing CLI tests**

Invoke `main(["investigate", fixture_path, "--format", "json"])`, parse stdout, and assert the incident, top attribution, hypothesis status, and Evidence list. Verify an invalid path exits nonzero without a traceback containing local secrets.

- [ ] **Step 4: Run tests and confirm failures**

Run: `cd backend && uv run pytest tests/evaluation/test_scorer.py tests/test_cli.py -q`

Expected: imports or CLI command resolution fail.

- [ ] **Step 5: Implement the scorer and CLI**

Use standard-library `argparse`; do not add a CLI framework. Serialize Pydantic models with `model_dump_json(indent=2)`. The CLI reads exactly the path supplied, never discovers databases, and writes no file unless a later phase adds an explicit artifact option.

- [ ] **Step 6: Add developer commands and ignore generated output**

`Makefile` targets:

```make
install:
	cd backend && uv sync --all-groups

test:
	cd backend && uv run pytest --cov=ad_rca --cov-report=term-missing

check:
	cd backend && uv run ruff check . && uv run pyright

demo:
	cd backend && uv run profitlens investigate ../fixtures/demo/pricing_error.json --format json
```

Ignore `.venv/`, Python caches, coverage output, `artifacts/`, frontend build output, and local `.env` files while retaining `.env.example` in later phases.

- [ ] **Step 7: Run the full Phase 1 acceptance suite**

Run: `make install && make check && make test && make demo`

Expected: static checks pass, all tests pass, and the demo emits valid JSON with `PAYOUT_PRICE_INCREASE`, `CONFIRMED`, and non-empty Evidence.

- [ ] **Step 8: Commit the runnable Phase 1 core**

```bash
git add fixtures backend/src/ad_rca/evaluation backend/src/ad_rca/cli.py backend/tests .gitignore Makefile
git commit -m "feat: ship runnable deterministic RCA demo"
```

## Phase 1 Completion Gate

Run from the repository root:

```bash
make check
make test
make demo
git status --short
```

Completion requires all checks to pass, the pricing demo to produce a cited `CONFIRMED` result, the quality demo to remain at or below `LIKELY`, no database dependency or SQL to exist in the Phase 1 package, and the worktree to contain only intentional changes.
