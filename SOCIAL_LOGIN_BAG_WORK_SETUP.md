# NuBagz X Login + Unified Bag Work Setup

This branch uses **X and Google** for social login/account linking through Privy and introduces the unified Bag Work challenge architecture. X is the only social provider used for automatic Bag Work verification in this release. TikTok is intentionally not enabled.

## 1. Development setup now — no live NuBagz domain required

Use the same Privy application already configured for NuBagz wallets.

1. In the Privy Dashboard, enable **Twitter/X** and **Google** as OAuth login methods.
2. During development, use Privy's default OAuth credentials. Privy explicitly recommends completing development with its default provider credentials before switching to your own production credentials.
3. Enable **Return user data in an identity token** for the Privy application.
4. Copy the application's ES256 identity-token verification public key/JWK for the backend.

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

`PRIVY_VERIFICATION_KEY` may be the public JWK JSON or a PEM public key. Never place a Privy app secret, X secret, bearer token or private signing key in the frontend.

With the Privy values configured, X login and X account linking can be exercised in a local/staging NuBagz environment before NuBagz has a final public domain.

## 2. NuBagz-owned X OAuth credentials — recommended before production

For production branding/control, create an X developer application for NuBagz and configure it as a **confidential client** using X's **Web App, Automated App or Bot** application type.

Use this exact OAuth redirect/callback URI in the X application:

```text
https://auth.privy.io/api/v1/oauth/callback
```

This callback belongs to Privy, so it is not necessary to wait for the final NuBagz website domain before creating the X OAuth application.

After X issues the application credentials, enter the X **Client ID** and **Client Secret** in the Twitter/X provider configuration inside the Privy Dashboard. Do not commit those credentials to GitHub.

OAuth 2.0 is the preferred/default path for this NuBagz login integration. The current NuBagz implementation does not require OAuth 1.0a.

## 3. X automatic Bag Work verification

The login identity and challenge verifier deliberately use separate credential paths:

- **Privy X OAuth** proves which X user is linked to the NuBagz account.
- **X API bearer token** is backend-only and lets NuBagz check public repost/like/follow activity.

Create or use the X developer application used by NuBagz, enable X API access/usage as required by X, then generate/copy its app-only bearer token into the backend environment:

```env
X_API_BEARER_TOKEN=your-server-side-x-api-bearer-token
X_API_BASE_URL=https://api.x.com/2
```

The bearer token must never be exposed through a `VITE_` variable or browser code.

Current automatic actions:

- `REPOST` — checks the X post's reposting users.
- `LIKE` — checks the X post's liking users.
- `FOLLOW` — resolves the target account and checks its followers.

NuBagz compares the returned X user ID against the provider-issued X user ID stored from Privy's verified X identity. A typed username is never accepted as proof.

Private/protected X activity, provider/API failures, rate limits, or activity X does not expose to the configured application are treated as **not verifiable** and do not automatically award points/rewards.

## 4. X configuration checklist

Repository/code configuration is complete when all of these are true:

- `VITE_PRIVY_APP_ID` is configured for the frontend.
- `VITE_PRIVY_CLIENT_ID` is configured if the Privy app uses one.
- `PRIVY_APP_ID` is configured for the backend.
- `PRIVY_VERIFICATION_KEY` contains the Privy identity-token public JWK/PEM.
- Twitter/X is enabled in Privy Login Methods.
- X login/account linking works and produces a `twitter_oauth` linked identity.
- `X_API_BEARER_TOKEN` is configured only on the backend.
- A real X repost, like and follow challenge can be verified against a linked X account.
- Re-verifying the same challenge cannot produce a second reward.

## 5. Architecture

New project-created work uses:

- `challenges` — one universal model for `SOCIAL`, `BAG_WORK`, `CONTENT`, `COMMUNITY`, `ONCHAIN`, and `CUSTOM` activity.
- `challenge_completions` — one idempotent user/completion record with a unique `(user_id, challenge_id)` constraint.
- `social_accounts` — verified provider identities linked to the NuBagz user.

`Campaign` remains the funded reward container so the existing reward inventory, user/platform/referral shares, BagBuilder attribution and ledger rules remain intact.

Legacy `missions` remain supported for existing Bags. New Bags created by the updated Creator Studio use `challenges` instead. A Bag cannot mix legacy missions and new challenges.

## 6. User experience

- `/login` and `/register`: X and Google social login plus existing email/password.
- **My Bag**: Connected Accounts for X and Google; X explicitly indicates Bag Work verification capability.
- `/app/work`: combined Bag Work feed with optional type filters.
- `/app/daily`: compatibility alias to the Bag Work feed.
- Creator Studio → New Bag: one Bag Work activity builder; Social is one activity type and X is its automatic provider.

The dedicated legacy Bounties route remains available for backwards compatibility but is removed from primary navigation so the main earning experience is not fragmented.

## 7. What still requires the account owner

The following values cannot be generated safely from source code and should never be committed to the repository:

- Privy identity-token verification key/JWK copied from the NuBagz Privy application.
- X Client ID and Client Secret if/when NuBagz switches from Privy's development credentials to custom X OAuth credentials.
- X API bearer token for automatic verification.

Once those account-level values are entered into the appropriate environment/dashboard settings, no further architectural change is required for X login or the existing X Repost/Like/Follow verification flows.
