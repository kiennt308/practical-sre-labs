#!/usr/bin/env bash
# Run Grafana k6 v2.4.0 closed vs open tests and USL capacity fitter.
# Author: Kien Nguyen | License: Apache-2.0
set -euo pipefail

export MSYS_NO_PATHCONV=1
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CH06_DIR="$(cd "${SCRIPT_DIR}/../ch06" && pwd)"
NET_NAME="orderflow-ch07-net"
K6_IMG="grafana/k6:2.4.0"
PY_IMG="python:3.11-slim"

cleanup() {
  docker rm -f orderflow-app payment-stub >/dev/null 2>&1 || true
  docker network rm "$NET_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
docker network create "$NET_NAME" >/dev/null

echo "[1/4] Starting payment-stub and orderflow-app..."
docker run -d --name payment-stub --network "$NET_NAME" \
  -v "${CH06_DIR}:/ch06:ro" "$PY_IMG" \
  python /ch06/02-payment-stub.py >/dev/null

docker run -d --name orderflow-app --network "$NET_NAME" \
  -p 8080:8080 -v "${CH06_DIR}:/ch06:ro" \
  -e "DOWNSTREAM_URL=http://payment-stub:9090/charge" \
  -e "PROTECTED=1" -e "INITIAL_LIMIT=32" -e "POOL_SIZE=32" \
  "$PY_IMG" python /ch06/01-orderflow-checkout-app.py >/dev/null

for _ in $(seq 1 20); do
  if curl -sf http://127.0.0.1:8080/healthz >/dev/null; then
    break
  fi
  sleep 0.3
done

echo "[2/4] Running k6 v2.4.0 CLOSED model (constant-vus)..."
docker run --rm --network "$NET_NAME" \
  -v "${SCRIPT_DIR}:/lab:ro" \
  -e "SCENARIO=closed" \
  -e "TARGET_URL=http://orderflow-app:8080/v1/checkout" \
  "$K6_IMG" run /lab/01-k6-closed-vs-open-model.js

echo "[3/4] Running k6 v2.4.0 OPEN model (ramping-arrival-rate)..."
docker run --rm --network "$NET_NAME" \
  -v "${SCRIPT_DIR}:/lab:ro" \
  -e "SCENARIO=open" \
  -e "TARGET_URL=http://orderflow-app:8080/v1/checkout" \
  "$K6_IMG" run /lab/01-k6-closed-vs-open-model.js

echo "[4/4] Fitting USL curve & Little's Law headroom..."
docker run --rm -v "${SCRIPT_DIR}:/lab:ro" "$PY_IMG" \
  python /lab/03-usl-littles-law-fitter.py \
  --csv /lab/02-usl-capacity-dataset.csv
