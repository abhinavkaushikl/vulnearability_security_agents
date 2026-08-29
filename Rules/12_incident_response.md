# Incident Response & Security Operations

> Rule pack version: `2026-08-28`  
> Control family: `IR`  
> Purpose: IR plan, escalation, regulatory decision trees, exercises, contacts, forensics, vulnerability closure and RCA.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| IR-01 | Maintain a documented incident response plan. | Manual evidence. | Roles, severity, communications, containment, recovery and post-incident steps are defined. | IR plan | No | Critical |
| IR-02 | Define detection-to-triage-to-containment escalation targets. | Tabletop exercise. | Security incidents have severity-based internal SLAs. | IR runbook | M | High |
| IR-03 | Include legal/regulatory notification decision trees. | Legal/security tabletop. | GDPR/DPDP/CERT-In/sector obligations are mapped where applicable. | Decision tree | M | Critical |
| IR-04 | Conduct incident exercises and validate recovery. | Tabletop/technical drill. | Exercises produce tracked actions and measurable outcomes. | Exercise report | M | High |
| IR-05 | Maintain contact lists and external coordination paths. | Manual review. | Internal owners, providers and regulators have current contact mechanisms. | Contact roster | No | High |
| IR-06 | Preserve forensic evidence and chain of custody where needed. | Runbook review. | Evidence collection does not destroy volatile data and access is logged. | Forensics SOP | M | High |
| IR-07 | Track vulnerabilities to closure with risk acceptance. | Ticketing review. | Critical/high issues have owners, due dates and documented exceptions. | Risk register | M | High |
| IR-08 | Perform post-incident root cause analysis and control improvements. | Review previous incidents. | Lessons learned are converted to backlog/control changes. | RCA reports | M | Medium |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.
