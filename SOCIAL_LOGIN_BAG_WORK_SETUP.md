# NuBagz X Login + Free Public-Post Bag Work Setup

This branch uses **X and Google** for social login/account linking through Privy and introduces the unified Bag Work challenge architecture. TikTok is intentionally not enabled.

X Bag Work verification in this branch does **not** require a paid X API plan or an `X_API_BEARER_TOKEN`. NuBagz verifies public proof posts through X's official oEmbed endpoint at `https://publish.x.com/oembed`, which X documents as requiring no authentication and not being rate-limited.

## 1. Development setup now — no live NuBagz domain required

Use the same Privy application already configured for NuBagz wallets.

1. In the Privy Dashboard, enable **Twitter/X** and **Google** as OAuth login methods.
2. During development, use Privy's default OAuth credentials.
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
SOCIAL_PROOF_SECRET=optional-long-random-secret
```

`PRIVY_VERIFICATION_KEY` may be the public JWK JSON or a PEM public key. `SOCIAL_PROOF_SECRET` is optional; if it is omitted NuBagz uses `JWT_SECRET` when generating per-user proof codes. Use a strong secret in production.

## 2. NuBagz-owned X OAuth credentials — optional before production

For production branding/control, NuBagz can create its own X developer application for OAuth login and enter its **Client ID** and **Client Secret** in the Twitter/X provider configuration inside Privy.

Use this OAuth redirect/callback URI in the X application:

```text
https://auth.privy.io/api/v1/oauth/callback
```

This is for **login/account linking only**. It is separate from Bag Work verification.

## 3. Zero-cost X Bag Work verification

- **Privy X OAuth** establishes which X username belongs to the NuBagz user.
- **X oEmbed** reads only the public post URL supplied by that user so NuBagz can verify the public proof.

For every X Bag Work activity, NuBagz generates a deterministic user/challenge proof code such as `NBZ-A1B2C3D4E5F6`.

The worker connects X, creates a public post containing the project requirement and proof code, pastes the post URL into NuBagz, and NuBagz confirms the oEmbed author matches the Privy-linked X username and the required proof content is present.

## 4. Supported free X activities

New Social Bag Work supports:

- `POST` — require a phrase in a public post.
- `MENTION` — require an X `@mention` in a public post.
- `HASHTAG` — require a hashtag in a public post.
- `LINK` — require a project/campaign link in a public post.

The previous paid-API activities are intentionally removed for new challenges: Like, Follow and Repost. Those actions cannot be reliably confirmed for free from X's public oEmbed output.

## 5. Anti-abuse controls

The free proof flow includes a different HMAC-derived proof code for every user/challenge pair, exact matching to the Privy-linked X username, public status URL validation, project-specific requirements, rejection of multiple NuBagz proof codes in one post, the existing unique completion constraint, and idempotent campaign settlement.

## 6. Limitations

This method only verifies **public X posts that X exposes through oEmbed**. Deleted, protected/private, unavailable or otherwise non-embeddable posts cannot receive automatic verification. It does not prove private likes, follower relationships, or native repost relationships.

That limitation is intentional so NuBagz can keep X Bag Work verification at zero X API cost without scraping or depending on a third-party paid API.

## 7. User experience

- `/login` and `/register`: X and Google social login plus existing email/password.
- **My Bag**: Connected Accounts for X and Google.
- `/app/work`: combined Bag Work feed.
- Social cards display the project requirement and the user's unique NuBagz proof code.
- **Create post on X** opens X compose with the requirement and proof code prefilled.
- The worker pastes the published X post URL and selects **Verify post**.
- Creator Studio → New Bag: Social → X offers Public Post, Mention, Hashtag and Share Link.

## 8. What still requires the account owner

For X/Google login, the account owner still needs to configure Privy: enable X and Google login methods, enable identity-token user data, provide the Privy verification public key/JWK to the backend, and optionally configure NuBagz-owned X OAuth Client ID/Secret before production.

No X API bearer token or paid X API credits are required for the public-post verification flow in this branch.
