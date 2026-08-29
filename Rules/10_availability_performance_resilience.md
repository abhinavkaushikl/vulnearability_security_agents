# Availability, Performance & Resilience

> Rule pack version: `2026-08-28`  
> Control family: `PERF`  
> Purpose: Core Web Vitals, API latency, traffic spikes, dependency failure, cache safety, backup/restore and synthetic monitoring.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| PERF-01 | Measure Core Web Vitals for key pages: LCP <=2.5s, INP <=200ms, CLS <=0.1 at the 75th percentile target. | RUM/field data; lab is supplementary. | 75th percentile meets good thresholds for key templates. | CrUX/RUM/Lighthouse | P | Medium |
| PERF-02 | Measure server/API latency by p50/p95/p99 for critical flows. | APM. | Organization-approved SLOs are met; exceptions have owners. | APM dashboards | P | High |
| PERF-03 | Protect checkout/search/catalog during traffic spikes. | Staging load test + capacity model. | Autoscaling, queueing, caching and graceful degradation keep key flows usable. | Load-test report | M | Critical |
| PERF-04 | Implement health checks, circuit breakers and dependency timeouts. | Chaos/staging test. | Slow/downstream failures fail safely and do not create retry storms. | Resilience test | M | High |
| PERF-05 | Use CDN/cache correctly without leaking personalized content. | Cache-control review + user/session test. | Private/personalized responses are not served cross-user. | Cache test | P | Critical |
| PERF-06 | Have backup/restore objectives and test them. | Manual evidence + restore drill. | RPO/RTO are defined and restore tests succeed. | BCP/restore evidence | M | Critical |
| PERF-07 | Protect queues/orders against duplicate delivery and replay. | Workflow test. | Message handling is idempotent and recoverable. | Queue metrics/logs | M | High |
| PERF-08 | Set synthetic monitoring for customer journeys. | Monitoring review. | Login/search/product/cart/checkout/payment journeys are checked continuously. | Synthetic monitors | P | Medium |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.
