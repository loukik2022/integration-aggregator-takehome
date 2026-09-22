import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  scenarios: {
    concurrency_10: {
      executor: 'constant-vus',
      vus: 10,
      duration: '15s',
      startTime: '0s',
    },
    concurrency_50: {
      executor: 'constant-vus',
      vus: 50,
      duration: '15s',
      startTime: '16s',
    },
    concurrency_100: {
      executor: 'constant-vus',
      vus: 100,
      duration: '15s',
      startTime: '32s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
  },
};

const BASE_URL = __ENV.TARGET_URL || 'http://localhost:8080';
const PROVIDER = __ENV.PROVIDER || 'mock-oidc';
const USER = __ENV.USER || 'alice';

export default function () {
  // 1. Trigger async token retrieval (returns 202 Accepted)
  const res = http.get(`${BASE_URL}/${PROVIDER}/${USER}`);
  check(res, {
    'status is 202': (r) => r.status === 202,
    'has location header': (r) => r.headers['Location'] !== undefined,
  });

  const location = res.headers['Location'];
  if (!location) {
    return;
  }

  // 2. Poll for token result
  let completed = false;
  for (let i = 0; i < 10; i++) {
    const pollRes = http.get(`${BASE_URL}${location}`);
    if (pollRes.status === 200) {
      const body = pollRes.json();
      if (body && body.status === 'completed') {
        completed = true;
        check(pollRes, {
          'has access_token': (r) => r.json('access_token') !== undefined,
        });
        break;
      }
    }
    sleep(0.05);
  }

  check(completed, {
    'token retrieval completed': (c) => c === true,
  });
}
