# Blameless Postmortem: INC-2026-114 (OrderFlow Checkout)

- **Incident ID:** `INC-2026-114`
- **Severity:** `SEV-1`
- **Date / Window:** `2026-11-12` (`02:09 UTC` to `02:36 UTC`, 27m)
- **Author / Facilitator:** Kien Nguyen (SRE Platform)
- **Status:** Reviewed — Systemic Action Items Tracked in Ledger

## 1. Customer & Error Budget Impact

Between `02:09 UTC` and `02:36 UTC` on `2026-11-12`, `order-service`
in `us-east-1` (`orderflow-prod`) experienced HTTP `503` failures on
`POST /v1/checkout`, peaking at an `8.4%` error ratio (`14.8x` burn).

- **Affected Services:** `order-gateway`, `order-service`,
  `payment-worker` via `orderflow-global-aurora`
- **Detection Delay (TTD):** `5.0m` via `OrderflowCheckoutFastBurnPage`
- **Mitigation Time (TTM):** `9.0m` post-alert (`Argo CD` rollback)
- **Budget Consumed:** `11.2m` of `21.6m` 30-day `99.95%` budget (`51.9%`)

## 2. Systemic Contributing Factors

1. **Unbounded Pool Wait + Leaked Idle Transactions:** `order-service`
   `v2.41.0` introduced a non-transactional retry wrapper that held
   `pgx` connections from `orderflow-global-aurora` across backoff
   sleeps, saturating `100/100` slots in `us-east-1`.
2. **Missing Pre-Prod Pool Saturation Gate:** CI synthetic tests ran at
   low concurrency and did not assert `db_pool_active / db_pool_max`.
3. **Absent Slow-Drain Canary Threshold:** Argo Rollouts promoted
   `v2.41.0` because initial 2m canary latency stayed under `250ms`
   before pool connections drained over the next 5 minutes.

## 3. Chronological Timeline (UTC)

- `02:09:00Z` — Argo CD completed sync of `order-service` `v2.41.0`.
- `02:13:42Z` — OTel exemplar `4bf92f3577b34da6...` recorded pool wait.
- `02:14:00Z` — `OrderflowCheckoutFastBurnPage` paged primary on-call.
- `02:15:30Z` — ICS roles (`IC`, `OL`, `CL`, `Scribe`) confirmed.
- `02:18:00Z` — `OL` traced exemplars to `orderflow-global-aurora`.
- `02:23:00Z` — `OL` rolled back `order-service` to `v2.40.9`.
- `02:36:00Z` — 5m checkout error ratio stabilized below `0.05%`.

## 4. What Went Well & Where Guardrails Helped

- MWMBR alerting fired in `5.0m` without waiting for static CPU alarms.
- OTel `v0.165` trace exemplars cut dependency isolation time to `4.0m`.
- Strict ICS separation kept `OL` focused on rollback rather than code
  debugging at 2:00 AM.

## 5. Systemic Action Items

- `PM-107` (`P0`): Enforce `pgx` max idle-in-tx timeout (`5s`) in code.
- `PM-108` (`P0`): Add `promtool` slow-drain regression guard to CI.
- `PM-109` (`P1`): Gate Argo Rollouts canary on Aurora pool utilization.
- `PM-110` (`P1`): Add Toxiproxy pool-stall soak test in pre-prod CI.
