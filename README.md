# OrderFlow Practical SRE — Companion Code Labs

Zero-cloud-bill labs, OpenSLO contracts, Sloth specs, Prometheus v3.16
rules and `promtool` tests, Alertmanager v0.35 routing, ICS playbooks,
blameless postmortem SQLite auditors, Toxiproxy fault harnesses, k6 v2.4
open-model load scripts, Chaos Mesh workflows, and toil economics tools:

> **Practical Site Reliability Engineering**
> *A Practical Guide to SLIs, Error Budgets, Multi-Window Burn-Rate*
> *Alerting, Incident Command, Load Shedding, Chaos Game Days, and*
> *Toil Elimination*
> *Practical Engineering Series — Volume 05 (Capstone)*
> **Author & Publisher:** Kien Nguyen
> **Repository:** `https://github.com/kiennt308/practical-sre-labs`

Copyright (c) 2026 Kien Nguyen. Companion manifests, rules, scripts, and
policies in this repository are licensed under **Apache-2.0**.

---

## Zero-Cloud-Bill Toolchain & Docker Images

Every chapter lab runs 100% locally with Docker and Python 3.11+
standard library (`stdlib` and `sqlite3`) with zero cloud spend:

- `prom/prometheus:v3.16.0` — `promtool check rules` and
  `promtool test rules` for MWMBR alert verification
- `prom/alertmanager:v0.35.0` — `amtool check-config` and
  `amtool config routes test` for vendor-neutral routing hygiene
- `ghcr.io/slok/sloth:latest` — Sloth `v0.16.0` SLO rule generation
- `ghcr.io/openslo/oslo:latest` — `oslo v0.13.0` OpenSLO `v1` validation
- `openpolicyagent/conftest:latest` — OPA Rego v1 guardrails via
  `policies/sre_guardrails.rego`
- `ghcr.io/shopify/toxiproxy:2.13.0` — deterministic TCP fault proxy
- `grafana/k6:2.4.0` — open-model arrival testing and OTLP telemetry
- `Python 3.11+` — pure `stdlib` and `sqlite3` analytics CLIs

---

## Canonical OrderFlow Production Baseline

- **Services:** `order-gateway`, `order-service`, `payment-worker`,
  `orderflow-global-aurora`, `orderflow-valkey-cache`,
  `orderflow-checkout`
- **Regions & Namespace:** `us-east-1`, `eu-west-1` (`orderflow-prod`)
- **Primary SLOs:** `99.95%` 30-day availability (`21.6m` budget) and
  `99.0% < 250ms` 30-day checkout latency

---

## Directory Index

```text
code-labs/
├── README.md        Zero-cloud-bill guide and Docker image matrix
├── policies/        OPA Rego v1 guardrails (sre_guardrails.rego)
├── ch01/            OpenSLO v1 contracts and error budget evaluator
├── ch02/            Sloth v0.16, Pyrra, MWMBR rules & promtool tests
├── ch03/            Alertmanager v0.35, Opsgenie exit & on-call audit
├── ch04/            ICS runbook, OTel v0.165 exemplars & triage CLI
├── ch05/            Blameless postmortem, CSV ledger & SQLite auditor
├── ch06/            Toxiproxy retry storms, shedding & retry budgets
├── ch07/            k6 v2.4 open-model tests, OTLP & USL curve fitter
├── ch08/            Chaos Mesh v2.8 workflows, Toxiproxy & FIS guards
└── ch09/            Toil <50% audit, idempotent runbooks & ROI model
```

---

## Quick Verification Commands

Run offline policy and evaluator checks from `code-labs/`:

```bash
docker run --rm -v "${PWD}:/work" -w /work \
  openpolicyagent/conftest:latest test \
  -p policies/sre_guardrails.rego \
  ch01/02-checkout-availability-slo.yaml \
  ch01/03-checkout-latency-slo.yaml \
  ch03/01-alertmanager-orderflow.yaml

python ch01/04-error-budget-policy-eval.py
```
