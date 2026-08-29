# EU Marketplace & Consumer Compliance

> Rule pack version: `2026-08-28`  
> Control family: `EU`  
> Purpose: GDPR applicability, rights, breach process, DSA trader traceability, dark-pattern risks, redress and consumer-information obligations.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| EU-01 | Apply GDPR controls when processing personal data of EU individuals, subject to applicability. | Legal/data governance review. | Processing principles, rights, safeguards and accountability are documented. | RoPA/privacy evidence | M | Critical |
| EU-02 | Support GDPR rights request handling within applicable timelines. | Synthetic DSR test. | Requests are verified, tracked and responded to within legal deadlines. | DSR records | M | High |
| EU-03 | Implement data breach assessment and notification workflow. | Tabletop. | Controller/processor responsibilities and applicable notification paths are defined. | Breach playbook | M | Critical |
| EU-04 | For online marketplaces, implement trader traceability and required seller information where DSA applies. | Seller onboarding review. | Required trader information and compliance commitments are collected before marketplace use. | Seller records | M | High |
| EU-05 | Avoid prohibited dark-pattern practices and ensure required transparency. | Manual UX review. | Choice architecture is fair; required disclosures are clear and non-deceptive. | UX review | M | High |
| EU-06 | Implement complaint/redress workflows appropriate to applicable DSA obligations. | Manual process test. | Users can exercise applicable complaint/appeal mechanisms and receive required explanations. | Process evidence | M | Medium |
| EU-07 | Observe consumer-information/withdrawal obligations applicable to the commerce model and jurisdiction. | Legal/product review. | Required pre-contract information and withdrawal processes are present where applicable. | Legal review | M | High |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.
