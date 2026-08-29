# Network, DNS, TLS & Edge Security

> Rule pack version: `2026-08-28`  
> Control family: `NET`  
> Purpose: DNS, TLS, HTTPS, HSTS, origin protection, DDoS/rate-limiting and SSRF-sensitive egress.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| NET-01 | Redirect HTTP to HTTPS without exposing sensitive content over HTTP. | HTTP request comparison. | HTTP returns redirect to HTTPS; no sensitive response body/cookie over HTTP. | curl/HTTP trace | P | High |
| NET-02 | Use current, secure TLS configurations; disable deprecated protocols/ciphers. | TLS handshake/config scan against authorized target. | TLS policy meets organization baseline and no deprecated protocol is accepted. | TLS scan | P | High |
| NET-03 | Enable HSTS on production origins; use includeSubDomains/preload only when operationally safe. | Inspect Strict-Transport-Security. | Header exists with organizationally approved max-age; includeSubDomains/preload where intended. | Response headers | P | Medium |
| NET-04 | Prevent certificate expiry and hostname mismatch. | TLS certificate inspection. | Valid certificate chain; correct SAN; expiry monitoring configured. | Certificate metadata | P | High |
| NET-05 | Protect DNS against unauthorized changes and use appropriate DNSSEC where justified. | DNS/registrar review. | Registrar MFA, change controls, restricted roles; DNSSEC enabled where architecture supports it. | Registrar/DNS evidence | P/M | High |
| NET-06 | Restrict origin exposure behind CDN/WAF/load balancer where intended. | Compare known origin ranges and access logs. | Origin is not unintentionally directly reachable or bypassing controls. | Network architecture | P/M | High |
| NET-07 | Segregate admin, payment and internal services from public web tier. | Network architecture + firewall review. | Least-privilege routing and explicit allowed flows are documented/enforced. | ACL/security group evidence | M | Critical |
| NET-08 | Ensure edge protections include DDoS/rate limiting where required by risk. | Config review + controlled load test in staging. | Protected flows have documented thresholds, escalation, and fail-open/fail-closed behavior. | WAF/CDN config | M | High |
| NET-09 | Detect origin bypass and SSRF-sensitive egress paths. | Manual review + safe canary in non-production. | Server-side requests are constrained by destination policy; metadata/internal ranges blocked. | SSRF test evidence | M | Critical |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.
