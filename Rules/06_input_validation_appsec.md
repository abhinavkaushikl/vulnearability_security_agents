# Input Validation & Application Security

> Rule pack version: `2026-08-28`  
> Control family: `APP`  
> Purpose: Injection, XSS, CSRF, redirects, file upload, deserialization/template risks and resource exhaustion.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| APP-01 | Prevent SQL/NoSQL/LDAP/OS command injection. | Static review + safe staging validation with benign test strings. | Queries/commands use parameterization or strong contextual encoding; no executable injection path. | Code/SAST + staging result | M | Critical |
| APP-02 | Prevent cross-site scripting (stored, reflected, DOM). | SAST/DAST in staging. | Untrusted input is correctly encoded/sanitized in each context. | DAST evidence | M | Critical |
| APP-03 | Use CSRF protections for state-changing browser requests where cookie auth is used. | Workflow test. | Cross-origin forged state change is rejected. | Staging evidence | M | High |
| APP-04 | Validate redirects and navigation targets. | URL parameter review. | Only allowlisted/safe destinations are accepted. | Code/test evidence | P | High |
| APP-05 | Secure file upload: type/size controls, storage isolation, malware scanning as appropriate. | Staging upload tests with harmless fixtures. | Executable content cannot be stored/served in an exploitable context. | Upload test | M | Critical |
| APP-06 | Protect template rendering and deserialization boundaries. | Code review + safe staging tests. | Untrusted data cannot invoke arbitrary templates/classes/commands. | Code/test | M | Critical |
| APP-07 | Return generic error responses; keep sensitive diagnostics server-side. | Trigger controlled application errors. | No secrets, stack traces, DB errors, internal paths or tokens are exposed. | Error response evidence | P | High |
| APP-08 | Protect against resource exhaustion / ReDoS / oversized input. | Static regex review + staged boundary tests. | Regex and parsing operations have bounded complexity and payload limits. | SAST/DAST | M | High |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.
