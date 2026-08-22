# NuBagz Social Login + Unified Bag Work Setup

This branch adds Google, X and TikTok login/account linking through Privy and introduces the unified Bag Work challenge architecture. TikTok and Google are identity/login only in this release. X additionally supports automatic verification for Repost, Like and Follow Bag Work.

## 1. Privy dashboard

Use the same Privy application already configured for NuBagz wallets.

1. Enable OAuth login providers: **Google**, **Twitter/X**, and **TikTok**.
2. Configure each provider's OAuth credentials and allowed redirect URLs for the NuBagz deployment domains.
3. In **User management → Authentication → Advanced**, enable **Return user data in an identity token**.
4. Copy the application's identity-token ES256 verification public key/JWK for the backend.

Frontend environment:

```env
VITE_PRIVY_APP_ID=your-privy-app-id
VITE_PRIVY_CLIENT_ID=your-client-id-if-used
```

Backend environment:

```env
PRIVY_APP_ID=your-privy-app-id
PRIVY_VERIFICATION_KEY='{"kty":"EC",...}'
```

`PRIVY_VERIFICATION_KEY` may be the public JWK JSON or a PEM public key. Never place a Privy app secret or private signing key in the frontend.

## 2. X automatic verification

Create/configure the X developer application used by NuBagz and provide its server-side bearer token:

```env
X_API_BEARER_TOKEN=your-server-side-x-api-bearer-token
X_API_BASE_URL=https://api.x.com/2
```

The bearer token is backend-only. The browser never receives it.

Current automatic actions:

- `REPOST` — checks the X post's reposting users.
- `LIKE` — checks the X post's liking users.
- `FOLLOW` — resolves the target account and checks its followers.

NuBagz compares the returned X user ID against the X identity signed into/linked through Privy. A typed username is not accepted as proof.

Private/protected X activity or activity that X does not expose to the configured app is treated as **not verifiable**, not automatically awarded.

## 3. Architecture

New project-created work uses:

- `challenges` — one universal model for `SOCIAL`, `BAG_WORK`, `CONTENT`, `COMMUNITY`, `ONCHAIN`, and `CUSTOM` activity.
- `challenge_completions` — one idempotent user/completion record with a unique `(user_id, challenge_id)` constraint.
- `social_accounts` — verified provider identities linked to the NuBagz user.

`Campaign` remains the funded reward container so the existing reward inventory, user/platform/referral shares, BagBuilder attribution and ledger rules remain intact.

Legacy `missions` remain supported for existing Bags. New Bags created by the updated Creator Studio use `challenges` instead. A Bag cannot mix legacy missions and new challenges.

## 4. User experience

- `/login` and `/register`: Google, X and TikTok social login plus existing email/password.
- **My Bag**: Connected Accounts panel for Google, X and TikTok linking.
- `/app/work`: combined Bag Work feed with optional type filters.
- `/app/daily`: compatibility alias to the Bag Work feed.
- Creator Studio → New Bag: one Bag Work activity builder; Social is simply one activity type.

The dedicated legacy Bounties route remains available for backwards compatibility but is removed from primary navigation so the main earning experience is no longer fragmented.
