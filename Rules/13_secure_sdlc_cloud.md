# Secure SDLC, Dependencies, Secrets & Cloud

> Rule pack version: `2026-08-28`  
> Control family: `SDLC`  
> Purpose: Threat modeling, CI security, SBOM, patching, secrets, repo/CI IAM, artifact integrity, cloud posture and containers.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| SDLC-01 | Threat-model major flows before release. | Design review. | Assets, trust boundaries, abuse cases and mitigations are documented. | Threat model | M | High |
| SDLC-02 | Run SAST, dependency scanning and secret scanning in CI. | Pipeline review. | Builds fail or warn according to severity policy; results are tracked. | CI logs | P | High |
| SDLC-03 | Maintain software bill of materials / dependency inventory where required. | SCA review. | Third-party components have owner/version/source information. | SBOM/SCA report | P | Medium |
| SDLC-04 | Patch critical vulnerabilities within defined internal SLA. | Vulnerability management review. | Patch/remediation times align with risk-based policy. | Tickets/patch reports | M | Critical |
| SDLC-05 | Separate production secrets from source code and developer workstations. | Secrets/config review. | Secrets live in managed vaults; rotations are auditable. | Vault/config | M | Critical |
| SDLC-06 | Protect CI/CD and source repositories with least privilege and MFA. | Repo/CI IAM review. | Privileged actions require strong auth and approvals where appropriate. | IAM/audit log | M | Critical |
| SDLC-07 | Sign/review production artifacts and protect deployment pipeline. | Build provenance review. | Only approved artifacts reach production; rollback is available. | Deployment evidence | M | High |
| SDLC-08 | Secure cloud storage, IAM and network controls by default. | Cloud posture review. | No public sensitive buckets, wildcard privileges or unneeded internet-exposed services. | CSPM/IAM evidence | P/M | Critical |
| SDLC-09 | Scan container images/base OS packages and remove unnecessary components. | Image/SCA scan. | Critical known issues are blocked or risk-accepted. | Image scan | P | High |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.
