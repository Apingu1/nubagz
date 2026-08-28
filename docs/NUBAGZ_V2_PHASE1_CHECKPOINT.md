# NuBagz V2 — Phase 1 Completion Checkpoint

## Status

Phase 1 is complete when the final Phase 1 branch CI is green and the phase is merged into `develop/nubagz-v2`. This file records the Phase 1 architecture and the verification steps that must remain true at that checkpoint.

## Phase 1 domain model

The user-facing V2 domain is:

`Project → Challenge → Submission → Verification → Project Reward`

Bag Work is the single discovery/feed surface for Challenges. `For You`, `New`, `Trending`, and `Watchlist` are feed modes, not separate product areas.

The existing `Campaign` database model remains internal compatibility plumbing until the Phase 3 canonical Challenge migration. Historical grouped records are preserved through a clearly labelled compatibility route; new V2 creation is one Project → one independent Challenge reward definition.

## Navigation

Primary navigation is intentionally consolidated:

- Core: Home, Bag Work, BagDrops, Swaps, My Bag
- Trust: Project Trust, My Trust
- Ecosystem: Leaderboard
- Account: Notifications, Activity
- Build: Creator Studio
- Admin: Admin, when authorised

Profile/Security expansion is intentionally deferred to Phase 2, where account state, sessions, MFA/passkeys and security controls are implemented. Phase 1 does not create empty placeholder pages for those future controls.

## Points and Trust

- Visible `BagScore` terminology is retired from the V2 experience.
- NuBagz Points are shown as the temporary participation representation in Phase 1.
- Creators do not configure Points.
- My Trust remains a separate integrity/risk signal and is not derived from the visible Points presentation.
- The existing `bag_score` / XP storage and compatibility behaviour remains internal until the planned Phase 5 Points ledger migration. It must not be treated as the final Points architecture.

## My Bag consolidation

My Bag is the user-owned portfolio/reward destination and contains:

- Overview
- Rewards and valuation/history
- Invites/referral information
- Wallet/social account controls already belonging to My Bag

Compatibility routes redirect:

- `/app/earnings` → My Bag Rewards
- `/app/referrals` → My Bag Invites

## Creator Studio

Creator Studio is organised around the V2 creator model:

- Overview — Projects, Project Trust and analytics entry points
- Challenges — independent Challenge definitions, Project Reward funding state and publication controls
- Submissions — only evidence configured for Project review
- Sponsored Gas — optional policies attached to on-chain Challenges

Project Trust management remains project-specific and private to creator controls. Public Project Trust stays read-only.

Creators create a Project first, then create independent Challenges. New Challenge creation defines one action, one verification route and one Project Reward. X, on-chain, quiz and project-reviewed verification paths remain supported. Sponsored gas remains an optional on-chain Challenge setting, not a standalone product area.

## Canonical Phase 1 API surfaces

Phase 1 introduces compatibility-safe Challenge-first surfaces, including:

- `GET /api/projects/{project_id}/challenges`
- `POST /api/projects/{project_id}/challenges`
- `GET /api/challenges/{challenge_id}`
- `POST /api/challenges/{challenge_id}/join`
- `GET /api/challenges/{challenge_id}/funding`
- `POST /api/challenges/{challenge_id}/funding/declare`
- `POST /api/challenges/{challenge_id}/funding/verify`
- `POST /api/challenges/{challenge_id}/pause`
- `POST /api/challenges/{challenge_id}/resume`
- `GET/POST/DELETE /api/challenges/{challenge_id}/watch`
- `POST /api/challenges/{challenge_id}/complete`

Reports can target a canonical `CHALLENGE` ID. Project analytics exposes Challenge-first fields while retaining old compatibility aliases for existing clients/tests until the Phase 3 migration.

## Retired or consolidated user-facing concepts

The following are no longer independent primary product destinations:

- Daily / For You / Discover / Trending / WatchBag → Bag Work feed modes
- Earnings → My Bag
- Referrals → My Bag / Invites
- Bounties → Bag Work
- Revenue Share → Creator Studio
- Templates → Create Challenge
- old Campaign builder → Create Challenge
- separate Gas area → on-chain Bag Work filter / Challenge configuration

Dormant source modules and old backend endpoints may remain where they are required for historical records or compatibility tests. They are not the canonical V2 domain and should be removed only during the appropriate later migration, not destructively during Phase 1.

## Historical grouped records

Old records containing multiple Challenge requirements under one reward container are not rewritten. `/app/bagz/:id` now provides a minimal, explicitly labelled pre-V2 compatibility view that links each requirement to its canonical Challenge page. This preserves historical data without presenting the old Bag/BagScore/XP architecture as the current model.

## Swap protection

Phase 1 must not alter the working Swap stack. The protected baseline includes:

- Privy RS256 authentication
- Robinhood RPC routing
- 0x
- LI.FI
- transaction construction/execution behaviour
- NuBagz fee: 75 bps / 0.75%

A final baseline-to-Phase-1 diff must confirm these files/configurations were not modified as part of Phase 1.

## Automated Phase 1 acceptance

Backend tests include a complete canonical lifecycle:

1. create Project
2. create Challenge through Project → Challenge API
3. declare and verify Project Reward funding
4. confirm Challenge appears in Bag Work
5. user watches and joins Challenge
6. user submits configured evidence
7. creator approves Project-reviewed evidence
8. Project Reward settles into earnings/My Bag data
9. community activity links to the canonical Challenge
10. Challenge pause/resume works through canonical endpoints
11. Challenge watch/unwatch works through canonical endpoints

A separate test verifies Challenge-targeted reporting and `SUSPEND_CHALLENGE` moderation.

The full CI gate also runs:

- backend pytest suite
- frontend TypeScript/Vite production build
- authoritative premium Bag Z checksum validation
- production frontend container build
- Phase 0 runtime safety checks
- production Docker Compose smoke test
- database checkpoint creation and checksum verification inside the disposable CI runtime
- SPA route checks

## Data safety

Phase 1 does not perform the Phase 3 Challenge schema migration or the Phase 5 Points ledger migration. Existing data therefore remains compatible with the Phase 0 database baseline.

CI verifies that the database backup/checkpoint mechanism still works. For the persistent development database, create the named Phase 1 checkpoint from the Codespace/server after pulling the merged integration branch:

```bash
bash scripts/backup_db.sh PHASE1_COMPLETE
```

Then verify the generated dump:

```bash
find backups -maxdepth 1 -type f -name '*PHASE1_COMPLETE*.dump' -print
bash scripts/verify_backup.sh backups/<generated-phase1-dump>.dump
```

Do not use `docker compose down -v` or `git clean -fdx` for ordinary development/update work.

## Manual verification checklist

After Phase 1 is merged into `develop/nubagz-v2`, verify these flows in the running application:

1. Sidebar contains the consolidated V2 navigation and no separate Earnings/Referrals/Bounties/Templates/Revenue Share discovery entries.
2. Home and Leaderboard use Points terminology; My Trust remains separate.
3. Creator Studio opens Overview / Challenges / Submissions / Sponsored Gas.
4. Create a Project, then create its first Challenge. Confirm there is no creator-configurable XP or BagScore control.
5. Verify the Challenge reward funding through the admin flow and confirm the Challenge appears in Bag Work.
6. Open the Challenge from Bag Work, join it and complete the configured verification path.
7. For Project-review work, confirm the submission appears in Creator Studio → Submissions and can be approved/rejected.
8. Confirm a completed Project Reward appears in My Bag → Rewards/History.
9. Confirm `/app/earnings` redirects to My Bag Rewards and `/app/referrals` redirects to My Bag Invites.
10. Open Reports and confirm the visible target choices are Project and Challenge.
11. If historical grouped records exist, confirm their old `/app/bagz/:id` link shows the pre-V2 compatibility screen and each requirement opens its canonical Challenge.
12. Open Swaps and verify quote/build behaviour remains operational and the NuBagz fee remains 0.75% / 75 bps.

## Deferred by design

The following are not Phase 1 omissions; they belong to later roadmap phases:

- canonical database-level Challenge/version/submission migration — Phase 3
- real Points ledger and removal of internal `bag_score`/XP compatibility — Phase 5
- full Profile/Security/account-state/session/MFA/passkey work — Phase 2
- NuBagz Eco implementation — Phase 7
