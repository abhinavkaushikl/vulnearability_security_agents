# India DPDP, CERT-In & Audit Controls

> Rule pack version: `2026-08-28`  
> Control family: `IN`  
> Purpose: DPDP obligations and phased rules, rights/grievance, CERT-In incident/log controls and audit evidence.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| IN-01 | Apply India DPDP Act obligations when processing digital personal data in scope. | Legal/data governance review. | Grounds, notice, consent/legitimate uses, rights and obligations are mapped. | DPDP mapping | M | Critical |
| IN-02 | Implement DPDP Rules 2025 controls according to their phased commencement dates. | Compliance calendar review. | Each rule is mapped to its effective date and implementation owner. | Compliance roadmap | M | High |
| IN-03 | Provide data principal rights/grievance mechanisms required by applicable DPDP provisions. | Synthetic request test. | Access/correction/erasure/grievance journeys are functional and auditable. | DSR/grievance log | M | High |
| IN-04 | Maintain incident response and reporting procedures aligned with applicable CERT-In directions. | IR tabletop. | Relevant incidents can be reported within required timelines and evidence is preserved. | IR/reporting playbook | M | Critical |
| IN-05 | Retain and protect logs according to applicable CERT-In requirements. | Log infrastructure review. | Required logs are enabled, protected and retained according to the applicable Indian rules. | SIEM/log policy | M | High |
| IN-06 | Include relevant CERT-In application-security and audit guidance in security assessments. | Audit-method review. | Assessment uses comprehensive vulnerability standards, not only a small “top 10” list. | Audit methodology | M | High |
| IN-07 | Capture audit evidence metadata: timestamps, versions, hashes where relevant, scope and tools. | Report review. | Evidence can be independently traced to the tested asset/version. | Audit report | P/M | Medium |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.
