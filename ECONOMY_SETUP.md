# NuBagz Economy Provider Setup

NuBagz separates **accounting and eligibility** from **external transaction execution**. The application must never mark a swap, gas sponsorship, withdrawal, or other crypto transaction successful merely because a user clicked a button.

## Core rule

Real-value user rewards remain project/partner funded. NuBagz founder capital is not used to subsidise campaign rewards, BagDrops, bounties, revenue-share pools, or sponsored gas budgets.

## Robinhood Chain

Robinhood Chain is the primary EVM network in NuBagz.

```text
Network name: Robinhood Chain
Chain ID: 4663
Native gas asset: ETH
RPC: https://rpc.mainnet.chain.robinhood.com
Explorer: https://robinhoodchain.blockscout.com
```

The official public RPC is configured by default for development. A dedicated production RPC/provider can replace it with `EVM_RPC_ROBINHOOD`.

## NuBagz Swap

The old draft/intent swap experience is retired from the user interface. NuBagz Swap requests **real executable same-chain EVM quotes** from 0x and LI.FI, presents a Route Race, and sends the selected provider transaction to the user's already-connected wallet for signature.

NuBagz never receives the user's private key, never signs the swap, and never treats a quote as an executed trade. A submitted transaction is accepted as a NuBagz swap receipt only after the backend verifies that the on-chain transaction:

- was sent by the verified NuBagz wallet;
- went to the exact router destination returned in the selected server-side quote;
- contains the exact quoted calldata;
- contains the exact quoted native transaction value; and
- has a successful chain receipt before it is marked confirmed.

For ERC-20 sells, the frontend checks the existing allowance and, when required, requests an **exact sell-amount approval** to the spender returned by the selected aggregator route. NuBagz does not request unlimited token approvals by default.

### Swap environment variables

```env
# Robinhood Chain / authoritative receipt verification
EVM_RPC_ROBINHOOD=https://rpc.mainnet.chain.robinhood.com

# 0x Swap API
ZEROX_API_KEY=

# LI.FI API / integrator account
LIFI_API_KEY=
LIFI_INTEGRATOR=nubagz

# NuBagz revenue layer. 75 bps = 0.75%.
NUBAGZ_SWAP_FEE_BPS=75

# EVM address that receives 0x integrator fees.
NUBAGZ_SWAP_FEE_RECIPIENT=0x...
```

`NUBAGZ_SWAP_FEE_BPS` is configurable and is capped by the application at 1,000 bps (10%). The current product default is **75 bps / 0.75%**. The fee is disclosed in the swap interface before wallet signature and is included in the executable provider quote rather than deducted from an internal NuBagz balance.

### NuBagz revenue path

**0x:** NuBagz passes the configured fee basis points and fee-recipient address to the 0x Swap API. The aggregator includes that fee in the executable route and directs the integrator fee to the configured NuBagz address.

**LI.FI:** NuBagz passes the configured `integrator` and `fee` values to LI.FI. The deployment must register/configure the `LIFI_INTEGRATOR` account with LI.FI so accumulated integrator fees can be attributed and withdrawn according to LI.FI's integrator mechanism.

The Route Race can continue when one provider is temporarily unavailable; the UI surfaces the executable routes that remain available. Production should configure both providers for better route coverage.

### Token and market data

Users select the native asset or ERC-20 contracts rather than entering free-form ticker symbols as the authoritative token identity. Token contract metadata is read from-chain, while DEX Screener is used for token/pool discovery and market context where available.

The market panel can display:

- DEX Screener chart embed;
- price;
- 24-hour change;
- liquidity;
- 24-hour volume;
- basic low-liquidity/new-pair signals; and
- a link to the full DEX Screener pair page.

These signals are informational only and must not be described as proof that a token is safe.

## Sponsored gas provider

Configure:

```env
GAS_SPONSOR_PROVIDER_BASE_URL=https://your-gas-adapter.example
GAS_SPONSOR_PROVIDER_API_KEY=optional-secret
```

Gas Pass is challenge-scoped. The project funds the gas pool and chooses limits such as time window, unique users, maximum claims, claims per wallet and total budget. Eligibility is reserved deterministically so concurrent users cannot exceed the configured caps. When sponsorship expires or is exhausted, the same on-chain Bag Work continues using normal user-paid gas.

When execution is requested, NuBagz sends the configured sponsor provider the verified user wallet, chain, budget cap and exact challenge transaction. NuBagz only debits the sponsor budget after a valid execution response containing a real transaction hash and a positive gas amount that does not exceed the reserved cap. If no gas provider is configured, sponsor inventory is unchanged and there is no founder-funded fallback.

## RPC verification

Authoritative on-chain challenge verification uses backend RPC values:

```env
EVM_RPC_ROBINHOOD=https://rpc.mainnet.chain.robinhood.com
EVM_RPC_AVALANCHE=
EVM_RPC_ETHEREUM=
EVM_RPC_BASE=
EVM_RPC_ARBITRUM=
EVM_RPC_POLYGON=
```

Do not expose provider API keys, fee-management credentials, or private RPC credentials to the frontend. Aggregator requests and authoritative receipt validation are performed by the backend; only the executable wallet transaction is handed to the user's connected wallet for signing.
