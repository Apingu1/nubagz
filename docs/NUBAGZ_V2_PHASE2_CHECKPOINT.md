# NuBagz V2 — Phase 2 Completion Checkpoint

Phase 2 is the Security, User Management & Trust programme. This checkpoint records the final launch architecture so later phases do not accidentally re-open settled security decisions.

## Completed Phase 2 scope

- Account lifecycle: ACTIVE, UNDER_REVIEW, RESTRICTED, SUSPENDED and DISQUALIFIED.
- Server-side sessions with revocation and session-bound JWTs.
- Production RS256 fail-closed authentication.
- Canonical Privy identity binding with provider-issued Google/X identities.
- Separate verified interactive signer and reward/payout destination roles.
- Exact active signer requirement for wallet-signed swaps and signer-dependent Challenges.
- Central Challenge dependency preflight and server-side dependency enforcement.
- Admin Users & Trust investigation, searchable/filterable with Trust reasoning and risk signals.
- Independent Account State, Trust, Reward Hold and Session controls with mandatory reasons.
- Support-led recovery controls for connected-login replacement and compromised wallet-link retirement.
- Login/security history and wallet/reward-role change history.
- TOTP Admin MFA, fresh primary-factor reauthentication and short-lived privileged Admin sessions.
- Explicit Admin permission scopes; SUPPORT is read-only for user investigation and ADMIN retains privileged mutation authority.
- Comprehensive privileged/Admin audit records and focused before/after user-action history.
- Privacy-preserving API throttling, suspicious burst analysis, optional Turnstile escalation and anti-Sybil signal combination.
- No single IP/device observation automatically restricts, suspends or disqualifies an account.
- Approved Project Rewards remain PENDING_SETTLEMENT until the future settlement engine confirms an on-chain payment.
- Creator Studio is Project-scoped and uses high-contrast, large navigation/action controls.

## MFA / passkey decision

The Phase 2 launch mechanism is TOTP MFA plus fresh password/Privy reauthentication and a short-lived privileged session. This satisfies the Phase 2 requirement for strong privileged Admin authentication without introducing a second partially implemented credential stack.

WebAuthn/passkeys are explicitly deferred as a later security enhancement. Adding passkeys must integrate with the same privileged-session and audit model rather than bypass it.

## Deliberately not pulled into Phase 2

- Manual Points adjustment and the canonical Points ledger belong to Phase 5.
- Canonical Challenge Requirements/Steps, immutable launched versions and the full Submission lifecycle belong to Phase 3.
- NuBagz Admin final Challenge Review / APPROVE-REJECT-HOLD workflow belongs to Phase 4.
- My Bag portfolio expansion belongs to Phase 6.
- Project Vault/Treasury funding is Phase 8.
- On-chain Project Reward settlement is Phase 9.

## Hard architectural rules carried forward

- Trust and Points are separate systems.
- A payout-only address never proves wallet ownership.
- NuBagz never treats an approved reward as Distributed before confirmed settlement.
- Creator ownership is enforced server-side.
- Sensitive Admin writes require both permission and fresh privileged access.
- Recovery never claims to recover MetaMask/private keys or blockchain funds.
- `main` remains untouched during the V2 programme; accepted work integrates through `develop/nubagz-v2`.
