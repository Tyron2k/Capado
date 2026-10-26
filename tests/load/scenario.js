import http from 'k6/http';
import { check, fail } from 'k6';
import exec from 'k6/execution';

const base = 'http://backend:3001/api';
const smoke = __ENV.LOAD_PROFILE === 'smoke';
if (!['full', 'smoke'].includes(__ENV.LOAD_PROFILE || 'full')) {
  throw new Error('LOAD_PROFILE must be full or smoke');
}
const p95 = Number(__ENV.LOAD_P95_MS || 1000);
const p99 = Number(__ENV.LOAD_P99_MS || 2000);
if (!(p95 > 0 && p99 >= p95 && Number.isFinite(p99))) {
  throw new Error('Latency budgets must be finite and 0 < p95 <= p99');
}
const endpoints = [
  { name: 'dashboard', path: '/dashboard?start_date=2026-01-05&end_date=2026-03-27' },
  { name: 'projects', path: '/projects/overview' },
  { name: 'gantt', path: '/gantt/resources/department/Synthetic%20review%20group' },
];
const thresholds = {
  'dropped_iterations{scenario:load}': ['count==0'],
  'http_req_failed{phase:measure}': ['rate<0.01'],
  'checks{phase:measure}': ['rate==1'],
};
for (const endpoint of endpoints) {
  thresholds[`http_req_duration{phase:measure,endpoint:${endpoint.name}}`] = [
    `p(95)<${p95}`, `p(99)<${p99}`,
  ];
  thresholds[`http_reqs{phase:measure,endpoint:${endpoint.name}}`] = [
    `count>=${smoke ? 10 : 1000}`,
  ];
}

export const options = {
  scenarios: {
    warmup: {
      executor: 'constant-arrival-rate', rate: 5, timeUnit: '1s',
      duration: smoke ? '3s' : '15s', preAllocatedVUs: 10, maxVUs: 10,
      gracefulStop: '10s', tags: { phase: 'warmup' },
    },
    load: {
      executor: 'ramping-arrival-rate', startRate: 5, timeUnit: '1s',
      stages: smoke ? [{ duration: '9s', target: 5 }] : [
        { duration: '20s', target: 20 }, { duration: '30s', target: 20 },
        { duration: '20s', target: 50 }, { duration: '30s', target: 50 },
      ],
      startTime: smoke ? '13s' : '25s',
      preAllocatedVUs: 50, maxVUs: 50, gracefulStop: '10s',
      tags: { phase: 'measure' },
    },
  },
  thresholds,
  summaryTrendStats: ['avg', 'p(50)', 'p(95)', 'p(99)', 'max'],
};

function read(endpoint, token, phase) {
  const response = http.get(`${base}${endpoint.path}`, {
    headers: { Authorization: `Bearer ${token}` }, timeout: '10s', redirects: 0,
    tags: { endpoint: endpoint.name, phase, name: endpoint.name },
  });
  let body;
  try { body = response.json(); } catch (_) { body = null; }
  const valid = response.status === 200 && body && (
    endpoint.name === 'dashboard'
      ? body.projects?.length === 83 && body.personal_utilization?.length > 0
      : body.projects?.length === 83
  );
  return check(response, { [`${endpoint.name}: complete populated response`]: () => !!valid });
}

export function setup() {
  const response = http.post(`${base}/auth/login`, JSON.stringify({
    email: 'load@example.test', password: 'disposable-load-test-only',
  }), { headers: { 'Content-Type': 'application/json' }, timeout: '10s' });
  if (response.status !== 200) fail(`Fixture login failed: HTTP ${response.status}`);
  const token = response.json('access_token');
  if (!token) fail('Fixture login returned no access token');
  for (const endpoint of endpoints) {
    if (!read(endpoint, token, 'preflight')) fail(`Invalid ${endpoint.name} fixture`);
  }
  return { token };
}

export default function (data) {
  // Exactly one request per iteration: configured arrival rates are total API RPS.
  read(endpoints[exec.scenario.iterationInTest % endpoints.length], data.token,
    exec.scenario.name === 'load' ? 'measure' : 'warmup');
}
