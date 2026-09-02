# ProfitLens Delivery Roadmap

**Spec:** `docs/superpowers/specs/2026-09-02-profitlens-design.md`

The product is split into three independently testable implementation plans.

## Phase 1: Deterministic RCA Core

Deliver a Python package and CLI that read immutable JSON fixtures, detect profit incidents, attribute loss, verify the five supported cause families, and emit an evidence-backed JSON report. No LangGraph, web API, frontend, model call, or database connection is included in this phase.

Plan: `docs/superpowers/plans/2026-09-02-profitlens-core-implementation.md`

## Phase 2: Agent Workflow and API

Wrap the Phase 1 engine in the bounded two-round LangGraph workflow. Add planner/composer protocols, fake and OpenAI-compatible implementations, in-memory checkpoints, JSONL run artifacts, FastAPI endpoints, SSE events, readonly ClickHouse/MySQL adapters, SQL AST enforcement, and integration tests.

This phase is complete when the three scenarios can be investigated through HTTP, streamed in real time, replayed from local files, and run without a live model through deterministic fallback behavior.

## Phase 3: Investigation Workbench and Portfolio Release

Build the React/TypeScript investigation workbench, waterfall and attribution views, graph timeline, evidence inspector, constrained follow-up panel, Playwright journey, 20-scenario evaluation suite, GitHub Actions, architecture documentation, screenshots, demo recording, and final README.

This phase is complete when a new user can run `make demo` without a database or API key and understand a full incident investigation in five minutes.

## Cross-Phase Gate

Every phase must retain these invariants:

- Database access is read-only and cannot be initiated by an LLM.
- Domain computations remain independent of LangGraph, FastAPI, and database drivers.
- Every conclusion cites structured evidence.
- Fake-model and fixture-mode tests run without network access.
- A phase starts only after the preceding phase test suite passes.
