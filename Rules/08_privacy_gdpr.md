# Privacy & Personal Data

> Rule pack version: `2026-08-28`  
> Control family: `PRIV`  
> Purpose: Privacy notice, minimization, retention, data-subject rights, transfers, consent/preferences and privacy incidents.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| PRIV-01 | Publish clear privacy information for data collection/processing. | Manual privacy notice review. | Notice explains purposes, categories, legal basis/grounds where required, retention, recipients and rights. | Privacy notice | M | High |
| PRIV-02 | Collect only necessary personal data. | Form/API/data-store review. | No unnecessary PII is requested or collected. | Data inventory | M | High |
| PRIV-03 | Define retention and deletion schedules. | Data inventory + sample deletion test. | Personal data is deleted/anonymized according to policy/legal need. | Retention schedule | M | High |
| PRIV-04 | Provide data subject rights workflows for applicable jurisdictions. | Test request process with synthetic account. | Access/correction/erasure/objection/etc. requests are routed, verified and fulfilled within legal timelines. | DSR workflow evidence | M | High |
| PRIV-05 | Control cross-border transfers and subprocessors. | Vendor/data flow review. | Transfers use appropriate legal and technical safeguards. | Vendor register | M | High |
| PRIV-06 | Minimize analytics/marketing identifiers and enforce consent/preferences where required. | Cookie/tag scan. | Non-essential tracking does not activate before required consent; opt-out is honored. | Tag manager logs | P/M | High |
| PRIV-07 | Protect privacy by design/default. | Design review. | Default settings minimize exposure and sharing. | Product settings | M | Medium |
| PRIV-08 | Protect children/minors where relevant. | Product/legal review. | Age-related requirements and consent controls are implemented where applicable. | Policy/workflow | M | High |
| PRIV-09 | Maintain breach assessment/notification process. | Incident tabletop. | Process maps discovery, containment, legal assessment and notices within applicable deadlines. | IR plan | M | Critical |
| PRIV-10 | Do not expose PII in logs, URLs, analytics or support tooling unnecessarily. | Log and telemetry scan. | Sensitive fields are redacted/tokenized and query parameters are minimized. | Sample logs | M/P | High |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.
