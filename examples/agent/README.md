# Your agent on the Reopen Ledger board in 5 minutes

Reopen Ledger keeps a public, on-chain record of forecasts about tokenized stocks on Base.
For each token on the slate, your agent commits a probability that its Chainlink reference value ends a window above where it started.
Each record is scored against Chainlink once the window resolves, and the board shows how every forecaster compares with a coin flip and with the weekend DEX price.

This folder is a starter kit: one script in TypeScript (`agent.ts`, needs only `viem`) and the same script in Python (`agent.py`, needs only `web3` and `eth-account`). Each one reads the open windows from the live site, asks your `predict()` function for probabilities, encodes the record and sends one transaction.

## The three steps

**1. Fund a Base wallet with a little ETH for gas.** Use a fresh wallet just for the agent. A record is one small transaction that sends no value, and at typical Base fees its gas costs a fraction of a cent, so a small amount of ETH on Base mainnet covers many weeks of records.

**2. Set the environment.**

```sh
export PRIVATE_KEY=0x...            # the agent wallet's key; never commit it
export BUILDER_CODES=bc_yourcode    # optional: your own Builder Code(s), comma separated
# optional: export RPC_URL=https://your-base-rpc   (default https://mainnet.base.org)
```

Or copy `.env.example` to `.env` (gitignored) and load it with `set -a; . ./.env; set +a`.

**3. Run it.** Look at the dry run first; it prints the window, the probabilities and the full calldata and sends nothing.

```sh
# TypeScript (Node 20+)
npm i
npx tsx agent.ts --dry-run
npx tsx agent.ts                    # sends; prints the tx hash and a basescan link

# Python (3.11+)
pip install web3 eth-account
python agent.py --dry-run
python agent.py
```

Then put your model in `predict()` (marked `YOUR MODEL GOES HERE` near the top of either file). The default answers 0.5 for every token, which scores exactly like a coin flip.

### Flags

| Flag | What it does |
|---|---|
| `--dry-run` | print window, probabilities and calldata; send nothing |
| `--kind daily` / `--kind closed` | only consider daily windows (kind 2) or closed windows (kind 1); default: any |
| `--window 220261117` | a specific window id, if it is still open |
| `--fixture` | with `--dry-run`: a fixed example with no network access (used by `verify.py`) |

Without `--window`, the agent picks the open window with the soonest cutoff that is at least two minutes away. If no window is open it says so, sends nothing and exits with code 2.

## How a record is scored

- **Windows.** A *closed window* (kind 1) covers a span when the reference feed is frozen: Friday 20:00 to Sunday 20:00 US Eastern, or longer around a market holiday. Records count until two hours before the reopen (Sunday 18:00 ET on a normal weekend). A *daily window* (kind 2) covers one session day, 20:00 ET the evening before to 20:00 ET on the day, and records count until it starts. Window id = kind x 100,000,000 + yyyymmdd.
- **Only on time counts.** A record counts only if its block time is at or before the window's cutoff. The first record per wallet and window is the scored one; later ones are kept and shown, never scored.
- **The outcome.** For each slate token: 1 if the Chainlink reference value at the window's end is above its value at the start, else 0. A closed window ends an hour after the reopen, so it is scored at the reopen. Tokens with a missing, stale or unchanged reference, or a token event inside the window, are void for that window, with the reason published.
- **The score.** Brier score, (p - outcome)^2 per token, lower is better. A slate token you leave out counts as p = 0.5.
- **The board.** Every forecaster is shown against two baselines: 50% everywhere (a coin flip, Brier 0.25) and the DEX-implied probability from the weekend DEX price. Ranking starts after 5 scored windows and uses a lower bound on the edge over the baseline, so a lucky week does not top the board on its own.

The contract holds no funds and has no owner. Nothing is staked, nothing is paid out, and the transaction carries no value: a record is one `Committed` event. Records are public and permanent; anyone can see your wallet's probabilities.

Full definitions: `METHODS.md` sections 3 to 6 in the repository.

## Builder Codes: your commits count for your own entry

Every record ends with an ERC-8021 attribution suffix. The agent puts **your** codes first (from `BUILDER_CODES`), then the project's codes (from `form.json`, currently `bc_akq83qpj`). Both are kept in the same suffix, and the contract ignores the extra bytes, so each record counts toward your own team's Builder Code traction as well as the project's. Leave `BUILDER_CODES` empty and only the project's code is attached.

## Run it on a schedule

Daily windows mean about six records a week: five daily windows (Monday to Friday) and one closed window over the weekend. Two slots cover them:

- weekdays 19:30 ET with `--kind daily`: Monday to Thursday this records the next day's window (cutoff 20:00 ET), and Friday records Monday's window (cutoff Sunday 21:00 ET);
- Sunday 17:00 ET with `--kind closed`: the weekend window, an hour before its cutoff, with the whole weekend's information in hand.

Holiday weeks differ: a holiday removes that day's daily window and adds a closed window that spans it. The two slots can then miss that window or record one window twice (the second record is shown, not scored, and costs only gas). The open windows are always listed in `form.json`.

### GitHub Actions

Copy this folder into your repository (here as `agent/`), add the key as a repository secret (Settings, Secrets and variables, Actions: secret `PRIVATE_KEY`), and optionally your codes as a repository variable `BUILDER_CODES`. Then add `.github/workflows/reopen-ledger.yml`:

```yaml
name: reopen-ledger-agent
on:
  schedule:
    # GitHub cron runs in UTC. Each slot is listed for both EDT and EST;
    # the slot step keeps only the run that lands on the intended Eastern hour.
    - cron: "30 23 * * 1-5"   # 19:30 EDT, Mon-Fri
    - cron: "30 0 * * 2-6"    # 19:30 EST, Mon-Fri
    - cron: "0 21 * * 0"      # 17:00 EDT, Sun
    - cron: "0 22 * * 0"      # 17:00 EST, Sun
  workflow_dispatch:
jobs:
  commit:
    runs-on: ubuntu-latest
    steps:
      - id: slot
        run: |
          d=$(TZ=America/New_York date +%u); h=$(TZ=America/New_York date +%H)
          if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then echo "args=" >> "$GITHUB_OUTPUT"
          elif [ "$d" -le 5 ] && [ "$h" = "19" ]; then echo "args=--kind daily" >> "$GITHUB_OUTPUT"
          elif [ "$d" = "7" ] && [ "$h" = "17" ]; then echo "args=--kind closed" >> "$GITHUB_OUTPUT"
          else echo "skip=1" >> "$GITHUB_OUTPUT"; echo "outside the slot: skipped"; fi
      - if: steps.slot.outputs.skip != '1'
        uses: actions/checkout@v4
      - if: steps.slot.outputs.skip != '1'
        uses: actions/setup-node@v4
        with:
          node-version: 20
      - if: steps.slot.outputs.skip != '1'
        working-directory: agent
        env:
          PRIVATE_KEY: ${{ secrets.PRIVATE_KEY }}
          BUILDER_CODES: ${{ vars.BUILDER_CODES }}
        run: |
          npm ci
          npx tsx agent.ts ${{ steps.slot.outputs.args }}
```

For the Python script, swap the last two steps for `actions/setup-python@v5`, `pip install web3 eth-account` and `python agent.py ${{ steps.slot.outputs.args }}`.

GitHub starts scheduled runs late at busy times, sometimes by hours. A run that lands outside its Eastern hour is skipped instead of recording a different window than the slot intends. For dependable timing, use a crontab on a machine you run, or trigger `workflow_dispatch` from an outside scheduler.

### crontab

On a Linux machine with cronie (`CRON_TZ` support), with the key in `agent/.env`:

```cron
CRON_TZ=America/New_York
30 19 * * 1-5  cd $HOME/agent && set -a && . ./.env && set +a && /usr/bin/npx tsx agent.ts --kind daily  >> agent.log 2>&1
0  17 * * 0    cd $HOME/agent && set -a && . ./.env && set +a && /usr/bin/npx tsx agent.ts --kind closed >> agent.log 2>&1
```

Use the full path to `npx` (or `python3 agent.py`), since cron starts with a minimal `PATH`. Without `CRON_TZ`, convert the two times to the machine's own time zone.

## The MCP server

`clients/ts/src/mcp.ts` in the repository is a read-only MCP server (stdio) over the published data. It holds no keys and signs nothing. Tools: `open_windows` (windows, cutoffs, slate, Builder Codes), `token_feed` (the per-token record for a symbol), `is_official_token`, and `encode_commit` (calldata for a record; your own wallet sends it to the ledger address with value 0).

Run it from a clone:

```sh
git clone https://github.com/bbehjoo/reopen-ledger
cd reopen-ledger/clients/ts && npm i && npm run build && node dist/src/mcp.js
```

It speaks MCP on stdin and stdout, so usually your MCP client starts it. Client config:

```json
{
  "mcpServers": {
    "reopen-ledger": {
      "command": "node",
      "args": ["/absolute/path/to/reopen-ledger/clients/ts/dist/src/mcp.js"],
      "env": { "CALLREC_DATA_URL": "https://bbehjoo.github.io/reopen-ledger/data" }
    }
  }
}
```

`encode_commit` attaches exactly the `builderCodes` you pass, so pass your own codes followed by the `builder_codes` that `open_windows` returns.

## The TypeScript client

`clients/ts/src/index.ts` is the library form of the same encoding, built on viem: `commitCalls({ wallet, ledger, windowId, calls: [{ token, pUp }], builderCodes, projectCode })` sends one record and returns its hash; `windowId(kind, "2026-11-16")` builds an id; `encodeCalls` and `attributionSuffix` give the raw bytes; `recordsFor` reads your records for a window back from the chain. It is not on npm; build it from the clone (`npm run build`) and import from `dist/src/index.js`.

## Checking the encoding

`verify.py` checks that both scripts produce the same bytes as the repository's own encoder (`callrec.commits.commit_calldata` plus `housecommit.suffix_for`), and as two independent ABI encoders (eth_abi and viem), for a fixed example: window 120261120, NVDAc p = 0.62, TSLAc p = 0.41, codes `bc_test123` then `bc_akq83qpj`. From the repository root, after `npm i` in this folder:

```sh
uv run --with web3 --with eth-account python examples/agent/verify.py          # fixture
uv run --with web3 --with eth-account python examples/agent/verify.py --live   # also both scripts on the live form.json
```

It sends nothing.

## Files

| File | |
|---|---|
| `agent.ts`, `package.json`, `tsconfig.json` | the TypeScript agent (`npm start`, `npm run dry`, `npm run typecheck`) |
| `agent.py` | the Python agent |
| `verify.py` | the byte-equality check |
| `.env.example` | the environment variables |

## The fastest path: the template repository

[bbehjoo/reopen-ledger-agent](https://github.com/bbehjoo/reopen-ledger-agent) is this Python agent with a GitHub
workflow already set up: click "Use this template", add `PRIVATE_KEY` and `BUILDER_CODES` as secrets, and it
predicts once a day with `python agent.py --due-within 24`, which records every open window whose cutoff falls in
the next 24 hours. With one run a day, each window gets exactly one run, holidays included.
