# Marketplace Trust, Fraud & Anti-Bot

> Rule pack version: `2026-08-28`  
> Control family: `ABU`  
> Purpose: Account creation abuse, credential attacks, scalping, gift cards/coupons, card testing, bot differentiation, seller verification and reviews.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| ABU-01 | Rate-limit and risk-score account creation. | Controlled staging traffic. | Burst/fan-out creation attempts are throttled/challenged without excessive false positives. | Bot/risk telemetry | M | High |
| ABU-02 | Detect credential stuffing and password spraying. | Security analytics review; use synthetic accounts in staging. | Multiple-account patterns trigger controls and alerts. | SIEM/risk rules | M | Critical |
| ABU-03 | Protect inventory against bot scalping/denial of inventory. | Staging/sandbox load tests. | Inventory locks, queueing, velocity limits and checkout controls prevent hoarding. | Order/inventory logs | M | High |
| ABU-04 | Protect gift-card, coupon and loyalty-value endpoints against enumeration/abuse. | Staging workflow tests. | High-entropy identifiers, rate limits, anomaly detection and step-up controls exist. | API tests | M | Critical |
| ABU-05 | Detect card testing / low-value authorization abuse with payment processor signals. | Fraud-rule review. | Velocity/device/IP/card fingerprint signals are used and outcomes are monitored. | Fraud rules | M | Critical |
| ABU-06 | Distinguish legitimate crawlers/accessibility/monitoring from abusive automation. | Bot policy review. | Allow/deny policy is documented; legitimate bots are not blanket-blocked. | Bot management policy | M | Medium |
| ABU-07 | Verify marketplace sellers/traders where required by applicable law. | Seller onboarding workflow. | Identity/contact/payment details and required certifications are collected and verified. | Seller KYC evidence | M | High |
| ABU-08 | Provide product/listing integrity controls. | Manual + moderation workflow. | Counterfeit/illegal/hazardous content processes exist with auditability. | Trust & safety SOP | M | High |
| ABU-09 | Protect reviews/ratings from manipulation and spam. | Abuse analytics review. | Controls limit fake review generation and coordinated manipulation. | Fraud/abuse metrics | M | Medium |
| ABU-10 | Implement account/device/IP risk telemetry with privacy safeguards. | Architecture review. | Signals are proportionate, access-controlled, retained appropriately and explainable. | Risk-data register | M | High |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.
