# ProfitLens reliability work

Database operations remain fixed, parameterized SELECTs. No production rows or credentials
are required in this repository.

1. Separate current-period totals from RCA. Preserve scope, aggregate in SQL, retain Decimal
   amounts, and distinguish empty results from zero revenue.
2. Reconcile detection and attribution baselines; expose decreases, increases and net change.
3. Handle improving losses, zero activity, missing history and bounded-query overflow explicitly.
4. Remove unsupported causal certainty; make evidence identities time/input dependent.
5. Exercise real MySQL SELECTs against synthetic derived tables and document remaining cloud
   checks (timestamp semantics, currencies, source-table relationships, retention).

Acceptance: independent totals agree; query limits never silently yield complete reports;
baseline/attribution amounts reconcile; lack of causal evidence never implies confirmed cause.

## Implemented and verified locally

- Summary routing executes only `period_totals` and preserves the requested scope. Monetary
  aggregates retain Decimal values, including a regression for a 0.02 difference in large totals.
- Detection and attribution use the same median-profit observations across all dimensions.
  Gross decreases, offsetting gains and net change are distinguished in report rendering.
- Improving negative profit with no loss paths reaches a zero-round insufficient-evidence
  report. Query-cap hits are refused as potentially incomplete. Chat survives query errors.
- Cap observations have unquantified loss and likely confidence. Report validation rejects
  changed confidence, changed loss and evidence borrowed from another hypothesis.
- Explicit real MySQL SELECT tests cover 100,000 synthetic source records, scope filtering,
  Decimal sums and an empty date window. No DDL or data mutations are used.
- Local CLI JSON amounts for 2026-09-10 matched an independently executed aggregate SELECT.

## Remaining deployment acceptance

Run `make docker-db-profile` on the cloud host and validate timestamp interpretation, actual
retention and missing values there. Compare one cloud summary with an independently reviewed
business SQL using exactly the same timezone, scope and source table. Do not interpret the
local synthetic test as cloud accounting validation.

Source-table relationships, currency consistency and late adjustments remain unverified.
Hourly RCA still requires hourly facts; summary queries do not. RCA still uses floating-point
metrics and bounded candidate discovery; it verifies only the largest loss path. Multisource
snapshot consistency and a full comparison/conversation router are separate follow-up work.
