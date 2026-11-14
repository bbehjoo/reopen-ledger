# RUNBOOK

Every chain write in this project goes through these steps. Commands run from the repo root with `.env`
present (`HOUSE_MNEMONIC`, `EXPORT_SIGNING_KEY`).

## 0. The automatic path (since 2026-11-10)

The `house` workflow runs `callrec house bootstrap` for Sepolia and then Base on every firing. On a network
where no ledger is recorded and the anchor wallet holds at least 0.002 ETH, it deploys CallLedger from the
anchor wallet's first transaction (nonce 0), records it in `config/ledger.yaml`, tops up the four house wallets,
and (Sepolia only) sends a test record twice; the job then commits `config/ledger.yaml`. If a job dies between
the deploy and the commit, the next run finds the contract at the anchor's nonce-0 address and records it
instead of deploying again (`tx.deploy_or_recover`, tested on Anvil). So sections 1 to 3 below are only needed
by hand when CI is not running. The Builder Code is already registered (section 2) and every house record reads
its own calldata back from the chain to confirm the code is there (`attribution` in each result).

## 1. Sepolia dry run (after the anchor wallet holds test ETH)

    uv run callrec house balances --network sepolia
    uv run callrec ledger deploy --network sepolia            # writes config/ledger.yaml: sepolia
    uv run callrec house fund --network sepolia --target-eth 0.002
    uv run callrec house commit-test --network sepolia --role null --window 120261113
    uv run callrec house commit-test --network sepolia --role null --window 120261113   # prints already_committed

Check the record on https://sepolia.basescan.org (contract address in config/ledger.yaml, event `Committed`).

## 2. Builder Code (one call, idempotent; ties a code to the anchor wallet)

    curl -s -X POST https://api.base.dev/v1/agents/builder-codes \
      -H "Content-Type: application/json" \
      -d '{"walletAddress": "0xe2C704A966d130C24F7DE0967E18d82521E6F4cc"}'

Response: `{"builderCode": "bc_...", "walletAddress": "0x..."}`. Done 2026-11-10: `bc_akq83qpj`, recorded in
`config/attribution.yaml`, which `ledger deploy` and every house record use by default.

## 3. Mainnet (after the anchor wallet holds about 0.003 ETH on Base)

    uv run callrec ledger deploy --network base            # Builder Code from config/attribution.yaml
    uv run callrec house fund --network base --target-eth 0.0004
    uv run callrec house commit-test --network base --role null --window <next window id>

Check that transaction on https://builder-code-checker.vercel.app/ (transaction hash, "Check
Attribution"). The house job records the deploy, every record and the checker's answer in data/house-log/.

From the deploy block on, the house schedule (METHODS.md section 7) applies, and the Monday check expects
every house record.

## 4. Off-PC scheduling (GitHub Actions, private repo)

1. Create a private GitHub repository and push this repo to it (`main`).
2. Add two repository secrets, `HOUSE_MNEMONIC` and `EXPORT_SIGNING_KEY`, with the values from `.env`.
3. In the Actions tab, run `seed-swaps` once by hand. It reads the swap streams from the chain since Aug 24
   (about an hour) and saves them to the Actions cache. Then run `daily` once by hand. From then on `daily`
   refreshes the cache every day, and `house` and `monday-check` restore it.
4. `house` fires three times in each slot (times and reasons at the top of `.github/workflows/house.yml`;
   `tests/test_schedule.py` checks them against the calendar). It first checks that the secret derives the
   published addresses, then bootstraps (section 0), then asks the chain which due records are missing
   (`house pending`); only then does it restore the swap cache and read data, so a firing with nothing owed
   costs about a minute. A DEX-implied record is never computed from swap data older than 2 hours: that slot
   errors and the job fails, which emails the owner. `monday-check` runs Monday 15:00 UTC and fails (emailing
   the owner) if a house record from the closed window is missing.
5. **Before DST starts on 2027-03-14**, move every house cron one hour earlier and extend the test's range.

## 5. Daily export by hand (when CI is not set up)

    uv run callrec ingest feeds && uv run callrec ingest b20 && uv run callrec ingest swaps
    uv run callrec ingest lending && uv run callrec snapshot all
    uv run callrec export --out data/exports/$(date -u +%Y-%m-%d)
    uv run callrec replay data/exports/$(date -u +%Y-%m-%d)
    uv run callrec site data/exports/$(date -u +%Y-%m-%d)
    uv run callrec house anchor data/exports/$(date -u +%Y-%m-%d) --network base   # writes to chain
