#!/usr/bin/env bash
# Live Toxiproxy v2.13.0 overload protection & retry hygiene lab.
# Author: Kien Nguyen | License: Apache-2.0
set -euo pipefail

export MSYS_NO_PATHCONV=1
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NET_NAME="orderflow-ch06-net"
TOXI_IMG="ghcr.io/shopify/toxiproxy:2.13.0"
PY_IMG="python:3.11-slim"

cleanup() {
  docker rm -f orderflow-app toxiproxy payment-stub \
    >/dev/null 2>&1 || true
  docker network rm "$NET_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
docker network create "$NET_NAME" >/dev/null

echo "[1/5] Starting payment-stub and Toxiproxy..."
docker run -d --name payment-stub --network "$NET_NAME" \
  -p 9090:9090 -v "${SCRIPT_DIR}:/lab:ro" "$PY_IMG" \
  python /lab/02-payment-stub.py >/dev/null

docker run -d --name toxiproxy --network "$NET_NAME" \
  -p 8474:8474 -p 8475:8475 "$TOXI_IMG" -host=0.0.0.0 >/dev/null

for _ in $(seq 1 20); do
  if curl -sf http://127.0.0.1:8474/version >/dev/null; then
    break
  fi
  sleep 0.5
done

echo "[2/5] Configuring proxy + 250ms (+/-50ms) latency toxic..."
curl -sf -X POST http://127.0.0.1:8474/proxies \
  -H "Content-Type: application/json" \
  -d '{"name":"payment","listen":"0.0.0.0:8475",
       "upstream":"payment-stub:9090"}' >/dev/null

curl -sf -X POST http://127.0.0.1:8474/proxies/payment/toxics \
  -H "Content-Type: application/json" \
  -d '{"name":"pay_latency","type":"latency","stream":"downstream",
       "toxicity":1.0,"attributes":{"latency":250,"jitter":50}}' \
  >/dev/null

run_phase() {
  local mode="$1"
  local prot="$2"
  docker rm -f orderflow-app >/dev/null 2>&1 || true
  docker run -d --name orderflow-app --network "$NET_NAME" \
    -p 8080:8080 -v "${SCRIPT_DIR}:/lab:ro" \
    -e "DOWNSTREAM_URL=http://toxiproxy:8475/charge" \
    -e "PROTECTED=${prot}" \
    -e "INITIAL_LIMIT=12" \
    -e "DOWNSTREAM_TIMEOUT=0.45" \
    "$PY_IMG" python /lab/01-orderflow-checkout-app.py >/dev/null

  for _ in $(seq 1 20); do
    if curl -sf http://127.0.0.1:8080/healthz >/dev/null; then
      break
    fi
    sleep 0.3
  done

  docker run --rm --network "$NET_NAME" \
    -v "${SCRIPT_DIR}:/lab:ro" "$PY_IMG" \
    python /lab/03-retry-storm-driver.py \
      --url http://orderflow-app:8080 \
      --downstream-stats http://payment-stub:9090/stats \
      --mode "$mode" --workers 24 --duration 6
  echo "--- /metrics ($mode) ---"
  curl -sf http://127.0.0.1:8080/metrics
}

echo "[3/5] Running NAIVE mode (no shedding, naive retries)..."
run_phase "naive" "0"

echo "[4/5] Running PROTECTED mode (AIMD + priority shed + budget)..."
run_phase "protected" "1"

echo "[5/5] Lab finished cleanly."
