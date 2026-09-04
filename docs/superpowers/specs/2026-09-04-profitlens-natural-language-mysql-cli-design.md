# ProfitLens Natural-Language MySQL CLI Design

**Date:** 2026-09-04  
**Status:** Approved for implementation planning

## Goal

Add a CLI experience in which a user can ask a Chinese business question such as
`分析昨天 offer 12345 为什么利润下降`, and ProfitLens safely translates it into a
bounded investigation over production MySQL data. The application must remain strictly
read-only: the model may select an analysis intent, but it may never create or execute SQL.

## User Experience

Provide two commands:

```bash
profitlens ask "分析昨天整体利润为什么下降"
profitlens chat
```

`ask` performs one investigation and prints a concise Markdown report; `--json` prints the
structured result. `chat` is a REPL. Its first analysis question starts an investigation,
later messages ask questions against that report, `/new` clears the current investigation,
and `/exit` quits.

Natural-language dates use `Asia/Shanghai` by default. An omitted time range means the
previous complete calendar day. An omitted business scope means the whole platform; the
agent then finds the largest loss-contributing advertiser, offer, channel, and country
slices before investigating them. Unsupported requests and ambiguous entity identifiers
produce a clear message rather than an unbounded query.

## Architecture and Data Flow

Use the existing bounded LangGraph workflow and deterministic RCA core:

```text
question
  -> DeepSeek intent parser
  -> strict AnalysisIntent validation
  -> fixed read-only QuerySpecs
  -> bounded MySQL data snapshot
  -> deterministic detection, attribution, and verification
  -> DeepSeek report composer (or deterministic fallback)
  -> Markdown/JSON CLI output and local replay artifacts
```

`AnalysisIntent` contains only the normalized time window, timezone, optional
`advertiser_id`, `offer_id`, `channel_id`, and `country`, plus the supported analysis kind.
The parser receives the current date and an allowlist of concepts. It receives no DSN,
schema details, SQL, or database rows. Invalid model output gets one repair attempt, then a
small deterministic parser handles explicit IDs and relative dates or returns a safe error.

The database loader materializes a bounded in-memory investigation snapshot and passes it
to the existing synchronous core. This keeps database drivers out of `domain`, `detection`,
and `rca` and avoids teaching the current algorithms how to execute queries.

## MySQL Sources and Mapping

ADN uses separate `DB20` and `DB40` connection settings, so ProfitLens accepts two MySQL
URLs. They may point to the same server when appropriate.

`au_stat.stat` is the hourly fact source:

| ProfitLens field | ADN field |
| --- | --- |
| event hour | `dt` |
| advertiser | `ader_id` |
| offer | `oid_` |
| channel | `aid` |
| country | `country` |
| OS / carrier | `clk_os` / `carrier` |
| clicks | `clk` |
| conversions | `cov` |
| channel-settled conversions | `cov_aff` |
| revenue / payout | `revenue` / `payout` |

The current window and eight historical comparable windows are aggregated in SQL by hour
and allowed dimensions. Profit is always calculated in Python as `revenue - payout`.
`cov_aff` is retained with its business meaning and is not silently relabeled as advertiser
approval when validation cannot establish that equivalence.

DB40 supplies supporting evidence:

- `ymgw.margin`: configured target margin.
- `ymgw.settlement`: current payout and settlement ratio.
- `ymgw.cap`, `cap_log`, and `remain_cap`: cap definition, hit interval, and utilization.
- `ymgw.redirect`: current routing target and update time.

These DDLs do not expose a complete price-change audit history. Therefore the agent must not
fabricate old configuration values. A change in effective `revenue/conversion` or
`payout/channel-settled-conversion` is metric-derived corroborating evidence; it becomes
direct configuration evidence only when a real history source is added later.

## Query Strategy and Safety

All queries are named, source-controlled `QuerySpec` objects with fixed tables, selected
columns, grouping, and literal limits. User and model values are bound parameters. Optional
scope predicates are implemented in the fixed templates; table or column identifiers never
come from input.

An unscoped request runs a staged investigation: overall time series first, then bounded
dimension contribution queries, then evidence queries only for the highest-loss slices.
The existing per-run limits remain mandatory: at most 20 queries, 10 seconds per query, and
10,000 rows per result. SQL is AST-validated immediately before execution. Multi-statements,
wildcards, locking reads, exports, remote functions, writes, and DDL remain rejected.

Both database users must be provisioned externally with `SELECT` only. ProfitLens exposes no
raw connection, generic `execute`, migration, schema-writing, or credential-display command.
DSNs use `SecretStr`; exceptions, prompts, reports, events, and artifacts are sanitized.

Configuration:

```dotenv
DATA_MODE=readonly_db
MYSQL_STAT_URL=mysql+asyncmy://readonly:secret@db20/au_stat
MYSQL_CONFIG_URL=mysql+asyncmy://readonly:secret@db40/ymgw
STAT_TIMEZONE=UTC
CLI_TIMEZONE=Asia/Shanghai
MODEL_MODE=deepseek
```

## Components

- Intent contracts and parser: validated natural language to `AnalysisIntent`.
- MySQL query catalog: fixed DB20/DB40 `QuerySpec` definitions.
- Snapshot loader/repository: maps aggregate rows and evidence into domain contracts.
- Conversation service: starts investigations and constrains follow-up questions to the
  current report and Evidence IDs.
- CLI commands: `ask`, `chat`, `db-check`, Markdown rendering, and `--json` output.
- Configuration wiring: selects fixture or MySQL mode without changing existing demos.

`db-check` performs only `SELECT 1`-style connectivity checks through the guarded read path
and reports each source without displaying its URL.

## Error Handling

Configuration errors name missing variables but never values. Authentication, timeout,
query-budget, no-data, ambiguous-input, and model-unavailable conditions have distinct safe
messages. Model failure may fall back to deterministic parsing/reporting when the request is
still unambiguous; database or mapping failures never produce an invented analysis.

## Testing and Acceptance

Unit tests cover intent validation, relative dates, prompt isolation, row mapping, timezone
conversion, every fixed query, read-only rejection, query budgets, and sanitized errors.
Fake MySQL clients and fake model clients drive deterministic service and CLI integration
tests. Existing fixture workflows remain offline and unchanged. Live database checks are
explicit and excluded from the default suite.

Acceptance requires:

1. `profitlens ask` turns representative Chinese questions into correct bounded intents.
2. Mocked DB20/DB40 data completes an evidence-backed RCA through the real workflow.
3. `profitlens chat` supports an initial investigation and cited follow-up questions.
4. Repository-wide tests prove no database write or model-generated SQL path exists.
5. `make test` and `make check` pass, and existing fixture commands remain compatible.
6. With externally configured read-only URLs, `db-check` and one real `ask` run succeed.
