# Repository Guidelines

## Project Structure & Module Organization

Application code lives in `backend/src/ad_rca/`. Keep domain contracts in `domain/`, deterministic detection and RCA logic in `detection/` and `rca/`, orchestration in `application/` and `workflow/`, and external adapters in `infrastructure/`. CLI rendering belongs in `presentation/`. Tests mirror these packages under `backend/tests/`. Synthetic scenarios are stored in `fixtures/demo/`; generated run artifacts stay under `backend/artifacts/` and must not be committed.

## Build, Test, and Development Commands

Run `make install` once to synchronize Python 3.12 dependencies with `uv`. Use `make test` for pytest plus coverage and `make check` for Ruff formatting/linting and strict Pyright. `make demo` runs the calculation-only fixture, while `make agent-demo` exercises LangGraph without an API key. `make model-check` checks DeepSeek connectivity, and `make dev` starts the fixture API. For read-only MySQL operation, use `make db-check`, `make ask QUESTION='分析昨天利润为什么下降'`, or `make chat`.

## Coding Style & Naming Conventions

Use four-space indentation, complete type annotations, and a 100-column maximum. Prefer frozen Pydantic contracts and small deterministic functions. Name modules and functions with `snake_case`, classes with `PascalCase`, and constants with `UPPER_CASE`. Run Ruff and Pyright before committing.

## Testing Guidelines

Use pytest. Name files `test_<feature>.py` and tests `test_<behavior>()`; avoid duplicate test module basenames in non-package directories. Add a failing test before changing behavior. Use fake model and database boundaries in the default suite; live checks must remain explicit. Do not reduce the existing coverage level.

## Commit & Pull Request Guidelines

Follow the repository history: `feat:`, `fix:`, `test:`, `docs:`, or `refactor:` plus an imperative summary. Pull requests should explain behavior, safety impact, commands run, and linked issues. Include CLI output for user-visible changes.

## Security & Configuration

Never commit `.env`, credentials, DSNs, or production rows. Database access is strictly read-only: do not add `INSERT`, `UPDATE`, `DELETE`, DDL, migrations, or raw execution APIs. SQL must remain fixed, parameterized, allowlisted, bounded, and independent of LLM output.
