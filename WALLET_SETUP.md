# NuBagz Wallet Setup

NuBagz supports three reward-destination modes:

1. **Embedded first wallet** — for new crypto users.
2. **Verified external wallet** — MetaMask, Rabby/other EIP-6963 browser wallets, Trust Wallet and other WalletConnect wallets.
3. **Payout-only address** — for users who do not want to connect a wallet to NuBagz at all.

The payout-only route works without any wallet-provider configuration. It never requests a signature or wallet permission and is intentionally marked `UNVERIFIED` in the NuBagz database.

## Wallet provider

NuBagz uses the Privy React SDK for embedded EVM wallets and external wallet connectors. The frontend is pinned to `@privy-io/react-auth` 3.37.1.

NuBagz keeps its own login/authentication system. Privy's custom JWT authentication is used to associate the authenticated NuBagz user with their user-controlled embedded wallet.

## 1. Create a Privy app

Create a Privy application in the Privy Dashboard and record the public **App ID** and optional **Client ID**.

In Privy, enable JWT/custom authentication for client-side use. NuBagz uses the JWT `sub` claim as the stable user ID.

## 2. Switch NuBagz JWT signing to RS256

Privy custom authentication requires asymmetric JWT verification. Generate a keypair outside the repository:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out nubagz-jwt-private.pem
openssl rsa -pubout -in nubagz-jwt-private.pem -out nubagz-jwt-public.pem
```

Never commit the private key.

Set these values in your deployment `.env`:

```env
JWT_ALGORITHM=RS256
JWT_KEY_ID=nubagz-1
JWT_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n
JWT_PUBLIC_KEY=-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----\n
VITE_PRIVY_APP_ID=your-privy-app-id
VITE_PRIVY_CLIENT_ID=your-client-id-if-used
```

NuBagz converts literal `\n` sequences back to PEM newlines at runtime.

## 3. Register the public verification key with Privy

In the Privy JWT/custom-auth configuration, use the contents of `nubagz-jwt-public.pem` as the public verification key. Configure the user ID/JWT ID claim as:

```text
sub
```

The NuBagz token issuer is:

```text
nubagz
```

## 4. Rebuild

The Privy App ID is compiled into the Vite bundle as a public frontend identifier, so rebuild the web container after changing it:

```bash
docker compose down
docker compose up -d --build
```

## Connected-wallet verification

A wallet being visible to the frontend is not enough for NuBagz. After creation/connection, the backend issues a one-time challenge containing the NuBagz username, wallet address, random nonce and issue time. The wallet signs that plain text message. The backend independently recovers the EVM signer address using `eth-account` before storing the wallet as verified.

This is a signature only. It is **not a transaction**, approval, permit or spend authorization.

## Payout-only security-first route

A user can instead save a reward address without connecting the wallet. NuBagz deliberately describes this as:

> If connecting a valuable wallet to a new website makes you uncomfortable — rightly so — don't. Simply add a deposit address for your NuBagz rewards. We will never request access to that wallet.

Payout-only addresses:

- require no wallet connection;
- require no signature;
- request no permissions;
- are stored as `UNVERIFIED` because NuBagz does not claim proof of wallet ownership;
- may be selected as the user's primary reward destination.

For production, changing a payout-only address should additionally be protected by account MFA and a withdrawal-address cooling-off period.
