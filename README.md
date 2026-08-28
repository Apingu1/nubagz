# NuBagz

**No money. No bag. No problem.**

NuBagz is a zero-deposit crypto participation platform. New users earn their way into crypto by completing funded project missions; projects can distribute token inventory without requiring a large upfront advertising budget; NuBagz earns a transparent share of completed reward flows.

## Product model

- **Earners** discover Bagz and complete Learn / Discover / Play / Create missions.
- **Projects** list free, pass a basic trust review, then create reward-backed Bag campaigns.
- **Campaign economics** split each completed campaign between the user, NuBagz, and a referrer/community allocation.
- **NuBagz does not fund user rewards.** A campaign cannot be created unless its declared allocation covers its maximum gross reward obligation.
- **BagScore + XP** reward genuine participation and create a path to higher-value opportunities.
- **Internal reward ledger** avoids forcing tiny on-chain transfers for every micro-reward. Users can request settlement to an external wallet.

## Complete earning economy

NuBagz includes verified campaign funding, an Earnings Centre, reward value tracking, BagDrops, Daily Earn, on-chain verification, Project Trust Scores, BagScore tiers, anti-Sybil controls, referral earnings, BagBuilder pathways, bounties, revenue share, smart recommendations, notifications, project analytics, campaign templates, ratings/reviews, reports/disputes, activity feed, Trending Bagz, WatchBag, swaps, sponsored gas and tax/earnings exports.

See `ECONOMY_SETUP.md` for external provider setup. Real custody, executable swap routing and live gas sponsorship remain provider-backed integrations rather than simulated transactions.

## Run

For the protected development/runtime path use:

```bash
bash run_stack.sh
```

The runner preserves an existing ignored `.env`, performs a non-secret runtime preflight, rebuilds the app containers, and keeps the PostgreSQL named volume intact.

Open `http://localhost:8080`.

Before significant branch/schema updates use:

```bash
bash scripts/pre_update_check.sh PRE_UPDATE
```

See `RUNTIME_DATA_SAFETY.md` for environment portability, verified database backups, safe Codespace shutdown and the forward-only NuBagz V2 branch workflow.

### Seeded development accounts

- Earner: `demo@demo.nubagz.com` / `Demo123!`
- Creator: `creator@demo.nubagz.com` / `Creator123!`
- Admin: `admin@demo.nubagz.com` / `Admin123!`

## Brand

**NuBagz**  
**No money. No bag. No problem.**

NuBagz is designed as an onboarding and participation economy, not a token launchpad and not a promise of investment returns.
