# Quay Markets

**Decentralized Exchange for Internet Capital Markets.**

Professional liquidity on permissionless rails. On Solana.

[**quay.markets →**](https://quay.markets)

---

## Architecture

```mermaid
flowchart TD
    MM1[MM]
    MM2[MM]
    MM3[MM]
    MM4[...]
    Relay["<b>Off-chain Relay</b> · TEE attested<br/>batches quotes · computes Merkle root"]
    Program["<b>Quay Program</b> · Solana<br/>shared vault · per-MM Merkle roots · safety bounds"]
    Takers[Takers]
    Aggs[Aggregators]
    DEX[DEX frontends]

    MM1 --> Relay
    MM2 --> Relay
    MM3 --> Relay
    MM4 -.-> Relay
    Relay -- "1 tx / 100ms · 123 markets" --> Program
    Program --> Takers
    Program --> Aggs
    Program --> DEX

    classDef pill fill:#ffffff,stroke:#1a1a1a33,color:#1a1a1a
    classDef accent fill:#E8764A1A,stroke:#E8764A,color:#1a1a1a
    classDef program fill:#ffffff,stroke:#1a1a1a,stroke-width:2px,color:#1a1a1a
    classDef leaf fill:#1a1a1a0D,stroke:#1a1a1a33,color:#1a1a1a

    class MM1,MM2,MM3,MM4 pill
    class Relay accent
    class Program program
    class Takers,Aggs,DEX leaf
```

---

## What Internet Capital Markets need

- **Tight spreads** — competitive with centralized venues
- **Permissionless MMs** — no gatekeeping by infra cost or relationships
- **Hundreds of pairs** — near-zero cost to quote a new market
- **Capital efficient** — shared collateral, not locked per-pair
- **Low LP/MM risk** — protection from toxic flow, not guaranteed losses

## How Quay solves it

Prop AMM is the closest model to what Internet Capital Markets need. Quay keeps everything that works and fixes what doesn't.

### Permissionless Quoting
Any market maker can start quoting any pair instantly — no onboarding, no infra setup. Router integrations (Jupiter, DFlow, Titan) are built in from day one.

### Batched Quote Streaming
Batched quotes drive the cost of quoting a market from **$100–1,000/day to $1–10/day**.

### Settlement Vault
LPs deposit USDC, SOL, ETH, BTC and other assets into a shared vault and earn trading fees. MMs use these deposits for instant settlement — only USDC collateral required, trading at 3–20× collateral size.

---

[quay.markets](https://quay.markets) · Built on Solana