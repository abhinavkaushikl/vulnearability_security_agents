# E-Commerce Critical Customer Journeys

> Rule pack version: `2026-08-28`  
> Control family: `FLOW`  
> Purpose: Browse/search/cart, price authority, inventory races, payment/order reconciliation, promotions, refunds, account changes and admin actions.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| FLOW-01 | Browse/search -> product -> cart flow works under normal and degraded dependency conditions. | Synthetic test. | Journey completes with expected UX and no data leakage. | Synthetic run | P | High |
| FLOW-02 | Price/tax/shipping calculations are server-authoritative. | Compare client vs server values in staging. | Client cannot alter final payable amount without server rejection. | Transaction trace | M | Critical |
| FLOW-03 | Inventory reservation and order placement are race-safe. | Staging concurrency test. | Overselling/negative inventory/duplicate reservation is prevented. | Concurrency report | M | Critical |
| FLOW-04 | Payment authorization and order creation are atomically reconciled. | Sandbox payment tests. | No paid-but-unordered or ordered-but-unpaid states without reconciliation process. | Payment/order trace | M | Critical |
| FLOW-05 | Coupons/promotions cannot be combined or replayed beyond policy. | Staging abuse tests. | Business rules are enforced server-side and logged. | Promo test | M | High |
| FLOW-06 | Refund/cancel/return workflows are authorization-safe and idempotent. | Staging workflow test. | Unauthorized/refunded-twice states are blocked. | Order ledger | M | Critical |
| FLOW-07 | Address and payment-method changes are protected by step-up controls. | Authenticated staging test. | Risky changes require appropriate re-auth/MFA and generate alerts. | Account audit trail | M | High |
| FLOW-08 | Support/admin order actions are fully audited. | Admin workflow test. | Actor, reason, before/after and timestamp are recorded. | Audit logs | M | High |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.
