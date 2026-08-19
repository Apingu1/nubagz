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

## Included product surfaces

### Public
- Futuristic responsive landing site
- Clear user and project value propositions
- Login / registration / referral onboarding

### Earner app
- Command-center dashboard
- Live Bag marketplace with search/categories
- Campaign detail and mission pathway
- Quiz verification and completion tracking
- BagXP, streak and BagScore
- Reward ledger and balances
- Withdrawal wallet configuration and withdrawal requests
- Referral code support
- Community leaderboard

### Creator Studio
- Project creation and review lifecycle
- Project roster
- Campaign creation with reward-allocation coverage validation
- User / NuBagz / referral split configuration
- Dynamic mission builder
- Learn / Discover / Play / Create mission types
- Campaign status and participation metrics

### Administration
- User/project/campaign overview
- Project approval/rejection
- Campaign go-live/suspension controls
- Platform reward-share treasury view
- Withdrawal settlement queue
- Fraud flag data model and overview metric

## Stack

- **Frontend:** React + TypeScript + Vite
- **Backend:** FastAPI + SQLAlchemy
- **Database:** PostgreSQL 16 in Docker (SQLite fallback for direct local backend development)
- **Auth:** JWT bearer tokens, scrypt password hashing
- **Deployment:** Docker Compose + Nginx reverse proxy

## Run the full stack

```bash
cp .env.example .env
# edit JWT_SECRET before exposing the service

docker compose up --build
```

Open `http://localhost:8080`.

### Seeded development accounts

These accounts are generated only when the database is empty:

- Earner: `demo@demo.nubagz.com` / `Demo123!`
- Creator: `creator@demo.nubagz.com` / `Creator123!`
- Admin: `admin@demo.nubagz.com` / `Admin123!`

Remove/replace demo seeding before any public production deployment.

## Local frontend development

```bash
cd frontend
npm install
npm run dev
```

The default frontend API target is `http://localhost:8000/api`.

## Local backend development

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Without `DATABASE_URL`, the API uses a local SQLite database for convenience.

## Reward accounting

If a campaign defines:

- gross completion reward: `1,000 TOKEN`
- user share: `80%`
- NuBagz share: `15%`
- referral share: `5%`

then one verified campaign completion creates ledger entries for:

- `800 TOKEN` → earner
- `150 TOKEN` → NuBagz platform treasury
- `50 TOKEN` → referring user, or community treasury if there is no referrer

This keeps NuBagz aligned with project performance instead of relying on founder-funded giveaways.

## Production hardening still required before handling real assets

The application is a complete product codebase and complete product UX, but real-money public operation requires operational integrations and external assurances that cannot be fabricated in source code:

- audited custody / wallet-provider integration or self-custodial settlement architecture
- project-token funding verification against chain state
- automated transaction signing / settlement with key-management controls
- independent security review and penetration testing
- anti-Sybil/device intelligence provider for high-value campaigns
- sanctions / AML / KYC controls where legally required
- legal review of promotions, token distributions, financial promotions, consumer disclosures and tax treatment in target jurisdictions
- production email / MFA / account-recovery provider
- rate limiting, WAF, observability, backups and incident response

The code deliberately represents withdrawals as a reviewed settlement queue rather than pretending to possess production custody credentials.

## Repository structure

```text
nubagz/
├── backend/
│   ├── app/
│   │   ├── routers/
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── security.py
│   │   └── seed.py
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── context/
│   │   ├── lib/
│   │   ├── pages/
│   │   └── styles.css
│   ├── Dockerfile
│   └── nginx.conf
└── docker-compose.yml
```

## Brand

**NuBagz**  
**No money. No bag. No problem.**

NuBagz is designed as an onboarding and participation economy, not a token launchpad and not a promise of investment returns.
