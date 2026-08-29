# Scope, Architecture & Audit Model

> Rule pack version: `2026-08-28`  
> Control family: `GOV`  
> Purpose: Scope, asset inventory, authorization, data classification and audit evidence.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| GOV-01 | Maintain a complete asset inventory: public domains, subdomains, APIs, mobile backends, admin portals, CDN/WAF, object storage, payment integrations. | Passive: enumerate DNS/cert transparency where authorized; Manual: reconcile CMDB/architecture. | Every production entry point has an owner, purpose, environment and risk classification. | Asset inventory + architecture diagram | P/M | High |
| GOV-02 | Define audit scope and authorization before active security tests. | Manual evidence review. | Written authorization identifies domains, APIs, test window, source IPs and prohibited actions. | Rules of engagement | No | Critical |
| GOV-03 | Classify data and trust boundaries. | Manual: data-flow diagram. | PII, payment data, secrets and internal/admin boundaries are documented. | Data-flow diagram | No | High |
| GOV-04 | Maintain a control-to-evidence matrix. | Manual. | Each applicable control maps to owner, evidence source, test result and remediation ticket. | GRC matrix | No | Medium |
| GOV-05 | Version the audit baseline and record test timestamp. | Manual/CI. | Every report states framework versions, scanner version, target, timestamp and environment. | Audit metadata | P | Low |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.
