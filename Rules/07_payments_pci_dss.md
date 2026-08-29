# Payments & PCI DSS

> Rule pack version: `2026-08-28`  
> Control family: `PCI`  
> Purpose: PCI scope, PAN/SAD handling, segmentation, vulnerability management, admin access, logs and third parties.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| PCI-01 | Define PCI scope/CDE and payment-flow architecture. | Manual evidence review. | Cardholder-data environment and all connected systems are identified; scope reduction decisions documented. | PCI scope diagram | M | Critical |
| PCI-02 | Avoid storing sensitive authentication data after authorization; use tokenization where possible. | Data-store/code/config review. | Payment data retention follows PCI requirements and processor architecture. | Data-flow/config | M | Critical |
| PCI-03 | Protect PAN in storage and transmission; mask/truncate displayed PAN. | UI/API/database review. | PAN is encrypted/tokenized as required; displayed PAN is minimized. | DB/UI evidence | M | Critical |
| PCI-04 | Segment CDE from unnecessary networks and systems. | Network diagram + firewall review. | Only required communications are allowed and documented. | Firewall/SG rules | M | Critical |
| PCI-05 | Maintain vulnerability management and secure configurations for in-scope systems. | Vulnerability reports/config baselines. | Critical/high findings are handled per risk policy and PCI requirements. | VA/patch reports | M | High |
| PCI-06 | Use strong authentication and unique IDs for administrative access to CDE. | IAM review. | No shared admin IDs; MFA enforced where required. | IAM evidence | M | Critical |
| PCI-07 | Centralize and protect audit logs; retain per applicable PCI policy. | SIEM/log review. | Security events are attributable, tamper-resistant and retained per requirement. | SIEM evidence | M | High |
| PCI-08 | Regularly test security controls and external exposure per PCI program. | Assessment/ASV evidence. | Required vulnerability scans/tests are current and findings addressed. | ASV/QSA evidence | M | High |
| PCI-09 | Verify third-party payment service providers and responsibilities. | Contract/attestation review. | Responsibilities and evidence are documented; provider status is current. | AOC/contract | M | High |
| PCI-10 | Never treat a web header/SSL scan as proof of PCI compliance. | Audit governance review. | Formal PCI assessment evidence exists where required. | AOC/ROC/SAQ | No | Critical |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.
