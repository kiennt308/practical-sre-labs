#!/usr/bin/env bash
# 05-verify-ch02.sh
# Validate Sloth v0.16 specs and promtool v3.16 MWMBR rule tests.
# Copyright (c) 2026 Kien Nguyen. Licensed under Apache-2.0.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_OUT="$(mktemp -d)"
trap 'rm -rf "${TMP_OUT}"' EXIT

echo "==> 1/5 Validating Sloth spec (sloth validate)"
docker run --rm -v "${ROOT_DIR}:/work" -w /work \
  ghcr.io/slok/sloth:latest \
  validate -i ch02/01-sloth-orderflow-checkout.yaml

echo "==> 2/5 Generating Prometheus rules via Sloth"
docker run --rm -v "${ROOT_DIR}:/work" -v "${TMP_OUT}:/out" -w /work \
  ghcr.io/slok/sloth:latest \
  generate -i ch02/01-sloth-orderflow-checkout.yaml \
  -o /out/sloth-generated-rules.yaml

echo "==> 3/5 Checking Sloth-generated rules via promtool"
docker run --rm --entrypoint=promtool \
  -v "${TMP_OUT}:/out" \
  prom/prometheus:v3.16.0 \
  check rules /out/sloth-generated-rules.yaml

echo "==> 4/5 Checking hand-authored MWMBR rules via promtool"
docker run --rm --entrypoint=promtool \
  -v "${ROOT_DIR}:/work" -w /work \
  prom/prometheus:v3.16.0 \
  check rules ch02/03-orderflow-mwbr-rules.yaml

echo "==> 5/5 Running deterministic promtool MWMBR unit tests"
docker run --rm --entrypoint=promtool \
  -v "${ROOT_DIR}:/work" -w /work \
  prom/prometheus:v3.16.0 \
  test rules ch02/04-orderflow-mwbr-tests.yaml

echo "Chapter 02 verification passed."
