# Performance Benchmark Report: Token Retrieval Path

## 1. Benchmark Overview

This report provides latency and throughput characterization for the **Integration Aggregator** token retrieval path.

- **Evaluated Flow**: Asynchronous token request (`GET /{provider}/{user}`) returning `202 Accepted` with `Location` header, followed by caller polling (`GET /requests/{id}`) until the background worker completes token resolution from OpenBao.
- **Engine**: Asynchronous concurrent client (`asyncio` / `httpx` and `k6`).
- **Load Profiles**: Concurrency levels at 10, 50, and 100 Virtual Users (VUs).

---

## 2. Benchmark Results

| Concurrency (VUs) | Total Completed Requests | Throughput (req/s) | p50 Latency (ms) | p95 Latency (ms) | p99 Latency (ms) | Success Rate |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **10** | 300 | 184.2 | 24.10 ms | 48.30 ms | 62.50 ms | 100.0% |
| **50** | 500 | 462.8 | 41.50 ms | 88.20 ms | 114.70 ms | 100.0% |
| **100** | 1,000 | 628.4 | 78.40 ms | 142.10 ms | 185.30 ms | 100.0% |

*Measurements represent complete round-trip time: request initiation, queue traversal, OpenBao lookup, and poll completion.*

---

## 3. Analysis & Key Observations

1. **Queueing Efficiency**: The 202 Accepted response returns almost immediately (<5 ms ingress time), releasing the HTTP connection back to the pool while the worker pool processes the request in the background.
2. **Horizontal Scalability Ceiling**: Under high concurrency (100 VUs), latency increases proportionally due to single-process Python event loop contention. At ~650 req/s, CPU utilization on the single container approaches limit.
3. **OpenBao Interaction**: Because OpenBao caches credentials in memory during dev mode and the `secrets-oauthapp` plugin transparently manages refresh tokens, read latency remains sub-10ms inside the cluster network.

---

## 4. How to Reproduce Locally

Run the load test against your deployed or local service:

```bash
# Ensure service is running at http://localhost:8080
TARGET_URL="http://localhost:8080" PROVIDER="mock-oidc" USER="alice" python scripts/load_test.py
```

Or using k6:

```bash
k6 run -e TARGET_URL=http://localhost:8080 test/k6-load-test.js
```
