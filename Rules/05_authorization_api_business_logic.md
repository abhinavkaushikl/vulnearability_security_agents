# Authorization, APIs & Business Logic

> Rule pack version: `2026-08-28`  
> Control family: `API`  
> Purpose: BOLA/BFLA, property authorization, API inventory, resource consumption, SSRF, debug exposure and idempotency.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| API-01 | Enforce server-side object-level authorization (BOLA prevention). | Two test identities in staging. | User A cannot read/modify User B objects by changing IDs or references. | API test | M | Critical |
| API-02 | Enforce function-level authorization for admin/operator endpoints. | Role matrix + test. | Low-privileged users cannot invoke privileged functions. | API test | M | Critical |
| API-03 | Apply property-level authorization; prevent mass assignment. | Staging API test. | Users can only write/read fields they are entitled to. | JSON request/response evidence | M | Critical |
| API-04 | Maintain complete API inventory and version lifecycle. | OpenAPI/config + runtime inventory. | Deprecated/unowned endpoints are removed or explicitly governed. | API inventory | P/M | High |
| API-05 | Limit resource consumption for expensive endpoints. | Controlled staging test. | Pagination, payload caps, concurrency/rate limits prevent unbounded consumption. | Load test | M | High |
| API-06 | Protect sensitive business flows from automation: checkout, coupons, inventory, gift cards, account creation. | Threat-model + staged test. | Abuse controls are flow-specific and preserve legitimate UX. | Flow control map | M | Critical |
| API-07 | Validate content type, size, schema and canonicalization at API boundaries. | Schema fuzzing in staging. | Unexpected/malformed inputs are rejected safely. | API validation logs | M | High |
| API-08 | Prevent SSRF in URL fetch/webhook/import functionality. | Staging canary test. | Private/link-local/metadata destinations are blocked and redirects revalidated. | SSRF evidence | M | Critical |
| API-09 | Disable debug/admin endpoints and introspection where not required in production. | Endpoint discovery + config review. | No exposed debug consoles, stack traces, unauthorized GraphQL introspection, test endpoints. | Discovery report | P/M | High |
| API-10 | Apply idempotency to non-idempotent financial/order operations. | Workflow test. | Retries do not create duplicate charges/orders. | Transaction logs | M | Critical |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.
