# Logging, Monitoring, Detection & Auditability

> Rule pack version: `2026-08-28`  
> Control family: `MON`  
> Purpose: Security-event logging, time sync, log integrity, account-takeover detection, WAF/DDoS telemetry, SLOs and telemetry privacy.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| MON-01 | Log authentication, authorization, payment, admin and high-risk business events. | SIEM/log review. | Events are attributable with timestamp, actor, action and outcome. | Sample logs | M | High |
| MON-02 | Synchronize system clocks. | Host/cloud config review. | Time sources are consistent enough for forensic correlation. | Time-sync config | P/M | Medium |
| MON-03 | Protect logs from alteration and unauthorized access. | IAM/storage/SIEM review. | Write access is restricted; integrity controls exist. | SIEM/storage policy | M | High |
| MON-04 | Alert on account takeover indicators and abnormal purchase behavior. | Detection-rule review. | High-risk patterns generate actionable alerts with owner/escalation. | SIEM rules | M | Critical |
| MON-05 | Monitor WAF/CDN/DDoS/rate-limit events. | Dashboard/log review. | Security teams can see volume, blocked traffic, attack types and affected endpoints. | Security dashboard | P | High |
| MON-06 | Track SLOs and error budgets for critical e-commerce flows. | APM/SRE review. | Availability/latency/error targets exist and drive operational action. | SLO dashboards | P | High |
| MON-07 | Keep audit evidence long enough for applicable legal/security requirements. | Retention policy review. | Retention is documented and jurisdiction-aware. | Retention policy | M | High |
| MON-08 | Avoid sensitive data in telemetry. | Sample traces/logs/analytics. | Secrets, PAN and unnecessary PII are masked/redacted. | Telemetry samples | M/P | Critical |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.
