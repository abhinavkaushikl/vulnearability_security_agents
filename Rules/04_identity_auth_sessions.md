# Identity, Authentication & Session Management

> Rule pack version: `2026-08-28`  
> Control family: `IAM`  
> Purpose: MFA, login/recovery, enumeration, password handling, session lifecycle and OAuth/OIDC.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| IAM-01 | Require MFA for privileged/admin/support access. | Manual policy + authenticated workflow test. | Admin roles require MFA; recovery flow does not silently bypass MFA. | IAM config | M | Critical |
| IAM-02 | Use rate limiting and abuse controls on login, password reset, OTP, account recovery. | Controlled staging test with test accounts. | Thresholds trigger throttling/challenge/lockout without enabling easy enumeration. | Auth logs + test run | M | Critical |
| IAM-03 | Do not reveal whether an account exists through login/reset responses. | Compare valid/invalid test accounts. | Externally observable responses are sufficiently uniform. | HTTP comparison | P | High |
| IAM-04 | Password policy and password storage follow current security guidance. | Code/config review. | Strong password hashing with unique salts; no reversible storage; no unsafe legacy hashes. | Code/config | M | Critical |
| IAM-05 | Support secure password reset with single-use, expiring tokens. | Staging workflow test. | Reset tokens expire, are single-use and are not logged or referrered. | Workflow evidence | M | Critical |
| IAM-06 | Require re-authentication for sensitive account changes and high-risk transactions. | Staging workflow. | Password/email/address/payment-method changes require appropriate step-up controls. | Workflow evidence | M | High |
| IAM-07 | Invalidate sessions after logout, credential reset and risk events. | Session lifecycle test. | Old session/token no longer authorizes protected actions. | Session test | M | High |
| IAM-08 | Use idle/absolute session timeouts suitable to risk. | Session config/test. | Timeouts are defined and enforced. | Config + test | M/P | Medium |
| IAM-09 | Protect OAuth/OIDC state, nonce, PKCE and redirect URI validation where applicable. | Protocol/code review. | No open redirect or authorization-code interception path in implemented flows. | OIDC config | M | Critical |
| IAM-10 | Provide secure account recovery, support-agent controls and anti-social-engineering safeguards. | Manual process review. | Support staff cannot bypass security without controlled, auditable verification. | Runbook/audit log | M | High |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.
