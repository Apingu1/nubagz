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

When configured, NuBagz sends `POST {SWAP_PROVIDER_BASE_URL}/quote`:

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

Configure:

```env
GAS_SPONSOR_PROVIDER_BASE_URL=https://your-gas-adapter.example
GAS_SPONSOR_PROVIDER_API_KEY=optional-secret
```

NuBagz first requires a project-owned gas budget whose maximum obligation is fully funded and manually verified. A participant must join a live campaign from the sponsoring project, have a verified EVM wallet, and pass trust controls before a gas request can be drafted.

When execution is requested, NuBagz sends `POST {GAS_SPONSOR_PROVIDER_BASE_URL}/sponsor`:

```json
{
  "wallet_address": "0x...",
  "chain": "Avalanche",
  "max_native_amount": "0.01",
  "transaction": {
    "to": "0x...",
    "data": "0x...",
    "value": "0x0"
  }
}
```

The adapter must execute or sponsor the real transaction and return:

```json
{
  "provider": "your-gas-provider",
  "request_id": "gas-123",
  "tx_hash": "0x...",
  "gas_spent_native": "0.0034"
}
```

NuBagz only debits the sponsor budget after a valid response containing an actual transaction hash and a positive gas amount that does not exceed the verified per-transaction cap. If no provider is configured, execution returns HTTP 503, the request remains a draft, and sponsor inventory is unchanged. There is no founder-funded fallback.

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
