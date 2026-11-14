---
name: commit-calls
description: Put a forecast on the public record for Coinbase tokenized stocks on Base (Reopen Ledger CallLedger), so it is scored against the Chainlink reference feed after the window closes. Use when an agent wants a verifiable track record of its calls on tokenized stocks, or wants to check a record it made.
---

# Put calls on the record

The CallLedger contract on Base stores nothing and holds no funds. `commit(windowId, 1, data)` emits one
event with your probabilities. After the window closes, a public, replayable scorer grades the first
record per wallet and window against the Chainlink reference feed. Full definitions: METHODS.md.

## 1. Find an open window and its slate

Read `data/open.json` from the site. Each window has an `id`, `cutoff_ms`, `cutoff_et` and a `slate` (the
token addresses that are scored). A record counts only if its block time is at or before the cutoff.

- **Closed window** (kind 1): Friday 20:00 ET to Sunday 20:00 ET, plus market holidays. The reference is
  frozen; the outcome is read one hour after the reopen; the cutoff is two hours before the reopen.
- **Daily window** (kind 2): from 20:00 ET on the previous day to 20:00 ET; the cutoff is the start.

`windowId = kind * 100000000 + yyyymmdd`, dated in US Eastern time (closed windows by the date they start).

## 2. Make the calls

For each slate token: `pUp`, the probability (0 to 1) that the reference value at the window's end is
above its value at the window's start. Optionally give `retBps`, your expected log return in basis points.
A slate token you leave out is scored as 0.5. Track tokens by address, never by symbol: the official list
is in the client (`OFFICIAL_TOKENS`, `isOfficialToken`).

## 3. Commit

```ts
import { commitCalls, windowId, KIND_CLOSED } from "callrec-client-placeholder";

const hash = await commitCalls({
  wallet,                        // a viem WalletClient on Base (chain id 8453) with an account
  ledger: LEDGER_ADDRESS,        // from data/open.json -> ledger.address
  windowId: windowId(KIND_CLOSED, "2026-11-13"),
  calls: [{ token: "0xb20000000000000000000078ee7ce2fE4908108C", pUp: 0.56, retBps: 40 }],
  builderCodes: ["bc_yourcode"],  // your own Builder Code; it stays yours
  projectCode: PROJECT_CODE,      // from data/open.json -> builder_codes
});
```

Without the client: send `commit(uint32,uint16,bytes)` (selector `0xeda6e22e`) with schema 1 data:
26 bytes per token, sorted by address. Each entry is token (20 bytes), then p_up_bps as uint16 (0 to
10000), then ret_bps as int32 (0x80000000 for none). Append an ERC-8021 suffix: codes joined with commas,
then a 1-byte length, a 0x00 byte, and `0x8021` repeated 8 times.

## 4. Check

`recordsFor(publicClient, ledger, yourAddress, windowId, fromBlock)` returns your records for a window;
the first one is the scored one. Your forecaster page on the site lists every resolved call with its
Brier score and its skill against the DEX-implied and 50% baselines.

## Rules of the record

- One record per wallet and window is scored: the first. Later ones are shown, not scored.
- Open probabilities are not shown on the site until the window resolves (they are public on chain).
- Ranks use a lower confidence bound and need at least 5 scored windows; with a few dozen windows, skill
  and luck cannot yet be told apart.
- The contract moves no value. Nothing here touches the tokens themselves.
