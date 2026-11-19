#!/usr/bin/env bash
# 04-verify-ch03.sh
# Validate Alertmanager v0.35 config, routes, and Rego guardrails.
# Copyright (c) 2026 Kien Nguyen. Licensed under Apache-2.0.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> 1/4 Checking Alertmanager config via amtool"
docker run --rm --entrypoint=amtool \
  -v "${ROOT_DIR}:/work" -w /work \
  prom/alertmanager:v0.35.0 \
  check-config ch03/01-alertmanager-orderflow.yaml

echo "==> 2/4 Testing critical route -> pager-oncall"
docker run --rm --entrypoint=amtool \
  -v "${ROOT_DIR}:/work" -w /work \
  prom/alertmanager:v0.35.0 \
  config routes test \
  --config.file=ch03/01-alertmanager-orderflow.yaml \
  --verify.receivers=pager-oncall \
  severity=critical slo=checkout-availability region=us-east-1

echo "==> 3/4 Testing warning route -> sre-slack-tickets"
docker run --rm --entrypoint=amtool \
  -v "${ROOT_DIR}:/work" -w /work \
  prom/alertmanager:v0.35.0 \
  config routes test \
  --config.file=ch03/01-alertmanager-orderflow.yaml \
  --verify.receivers=sre-slack-tickets \
  severity=warning slo=checkout-availability region=eu-west-1

echo "==> 4/4 Running Conftest Rego guardrails"
docker run --rm -v "${ROOT_DIR}:/work" -w /work \
  openpolicyagent/conftest:latest test \
  -p policies/sre_guardrails.rego \
  ch03/01-alertmanager-orderflow.yaml

echo "Chapter 03 verification passed."
