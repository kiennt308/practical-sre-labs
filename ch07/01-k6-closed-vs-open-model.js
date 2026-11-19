// OrderFlow closed-model vs open-model capacity lab (Grafana k6 v2.4.0).
// Author: Kien Nguyen | License: Apache-2.0
// Repo: https://github.com/kiennt308/practical-sre-labs
//
// Telemetry note: Grafana k6 v2.4.0 deprecated built-in InfluxDB and
// Prometheus remote-write outputs (for removal in k6 v3). Stream metrics
// via OTLP: K6_OTEL_GRPC_EXPORTER_ENDPOINT=otelcol:4317 k6 run -o
// opentelemetry 01-k6-closed-vs-open-model.js

import http from 'k6/http';
import { check } from 'k6';

const SCENARIO = __ENV.SCENARIO || 'open';
const TARGET_URL =
  __ENV.TARGET_URL || 'http://orderflow-app:8080/v1/checkout';

const scenarios = {};
if (SCENARIO === 'closed') {
  scenarios.closed_vus = {
    executor: 'constant-vus',
    vus: 16,
    duration: '10s',
  };
} else {
  scenarios.open_arrivals = {
    executor: 'ramping-arrival-rate',
    startRate: 15,
    timeUnit: '1s',
    preAllocatedVUs: 16,
    maxVUs: 48,
    stages: [
      { target: 35, duration: '4s' },
      { target: 35, duration: '6s' },
    ],
  };
}

export const options = {
  scenarios,
  thresholds: {
    http_req_failed: ['rate<0.005'],
    http_req_duration: ['p(95)<250'],
  },
};

export default function () {
  const params = {
    headers: { 'Content-Type': 'application/json' },
    timeout: '2s',
  };
  const res = http.post(TARGET_URL, '{"order_id":"ord-101"}', params);
  check(res, {
    'status is 200': (r) => r.status === 200,
  });
}
