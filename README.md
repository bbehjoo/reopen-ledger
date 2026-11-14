# Reopen Ledger

Coinbase's tokenized stocks trade around the clock on Base. Their Chainlink reference price, the one lending
markets read, is frozen from Friday 20:00 to Sunday 20:00 ET and on market holidays. This project measures
what that means:

- **What these markets can absorb.** Pool depth below the price, set against the collateral that Aave V4 and
  Morpho Blue would liquidate if the reference reopened 5%, 10% or 20% lower.
- **The weekend tape.** How far the token pools drift from the frozen reference, and how close the weekend
  DEX price comes to the value the reference shows when it reopens. Every closed span since Aug 24.
- **Calls on the record.** Anyone (agents first) puts a probability per token on the record in a contract
  that holds no funds. Each record is scored against the reference feed after its window closes, against
  the weekend DEX price and against 50%.

Measurements, not verdicts. Every published number is replayable from the raw chain logs (`callrec replay`),
every export is signed, and its hash is put on chain daily. Definitions: [METHODS.md](METHODS.md).

Site: https://bbehjoo.github.io/reopen-ledger/ (rebuilt from each daily export).

Put a call on the record: the site's form, the TypeScript `commitCalls` in `clients/ts/`, or the agent skill in
`skills/commit-calls/`. The contract address is in `config/ledger.yaml` once deployed.

Coinbase tokenized stocks are offered only to persons in eligible jurisdictions outside the United States.
This project records forecasts and publishes measurements; it routes no trades and holds no tokens.

## Layout

| Path | What |
|---|---|
| `METHODS.md` | every definition; versioned and stamped on every export |
| `config/` | chain facts, the official token registry, feeds, pools, lending markets, calendar, house wallets; every value with its source |
| `contracts/` | `CallLedger.sol` (event-only) and its Foundry tests |
| `src/callrec/` | ingest, scorer, tape, depth engine, lending math, build, export and replay, site, house jobs |
| `clients/ts/` | `commitCalls` (viem), the official-token list, an MCP server |
| `skills/commit-calls/` | the agent skill |
| `site/static/` | styles and the no-build web form |
| `data/raw/` | raw chain logs and snapshots (swap logs are re-read from the chain, see METHODS section 2) |
| `docs/research/` | lending markets, pools, feed hours, depth check |
| `data/exports/` | one signed export per day: every published file and its manifest |
| `data/house-log/` | every transaction of the project's own (house) wallets |

## Dev

    uv sync
    uv run pytest                                  # Python tests
    cd clients/ts && npm ci && npm test            # TypeScript client
    cd contracts && forge test                     # contract (Foundry)
    uv run callrec --help

A full run by hand is in [docs/RUNBOOK.md](docs/RUNBOOK.md).

Code: Apache-2.0 (`LICENSE`). Data: CC-BY-4.0 (`DATA-LICENSE`).
