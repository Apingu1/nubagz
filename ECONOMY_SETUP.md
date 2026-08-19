# NuBagz Economy Provider Setup

NuBagz deliberately separates **accounting and eligibility** from **external transaction execution**. The repository must never mark a swap, gas sponsorship, withdrawal, or other crypto transaction successful merely because a user clicked a button.

## Core rule

Real-value user rewards remain project/partner funded. NuBagz founder capital is not used to subsidise campaign rewards, BagDrops, bounties, revenue-share pools, or sponsored gas budgets.

## Swap routing provider

Configure:

```env
SWAP_PROVIDER_BASE_URL=https://your-routing-adapter.example
SWAP_PROVIDER_API_KEY=optional-secret
```

When configured, NuBagz sends:

`POST {SWAP_PROVIDER_BASE_URL}/quote`

```json
{
  "wallet_address": "0x...",
  "chain": "Avalanche",
  "sell_asset": "USDC",
  "buy_asset": "AVAX",
  "sell_amount": "10",
  "max_slippage_bps": 100
}
```

The adapter must return an unsigned transaction request:

```json
{
  "provider": "your-provider",
  "quote_id": "quote-123",
  "buy_amount": "0.25",
  "expires_at": "2026-08-19T21:00:00Z",
  "transaction": {
    "to": "0x...",
    "data": "0x...",
    "value": "0x0",
    "chainId": 43114
  }
}
```

NuBagz stores the quote and unsigned transaction. The user's verified wallet is responsible for signing and broadcasting it. If no provider is configured, quote requests return HTTP 503 and the intent remains a draft. No ledger debit or synthetic execution occurs.

## Sponsored gas provider

The gas sponsorship integration uses these environment variables:

```env
GAS_SPONSOR_PROVIDER_BASE_URL=https://your-gas-adapter.example
GAS_SPONSOR_PROVIDER_API_KEY=optional-secret
```

The provider must only be called after NuBagz has verified a sponsor-funded gas budget and an eligible request. The gas integration must never fall back to founder-funded execution when sponsor inventory is unavailable.

The concrete request/response contract is documented alongside the Sponsored Gas router once that integration is enabled.

## RPC verification

Authoritative EVM mission verification uses the configured RPC values:

```env
EVM_RPC_AVALANCHE=
EVM_RPC_ETHEREUM=
EVM_RPC_BASE=
EVM_RPC_ARBITRUM=
EVM_RPC_POLYGON=
```

Do not expose provider API keys or private RPC credentials to the frontend. All provider calls are made by the backend.
