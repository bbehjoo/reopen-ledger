# METHODS (version 0.2.0)

Reopen Ledger publishes three things about Coinbase-issued tokenized stocks on Base:

1. **Calls on the record.** Anyone can put a forecast on the record in a public contract before a window
   opens; every forecast is scored against the Chainlink reference feed after the window closes.
2. **The weekend tape.** While the reference feed is frozen (nights are not frozen; weekends and market
   holidays are), the tokens keep trading on DEXs. The tape measures how far the DEX price moves from the
   frozen reference, and how close the weekend DEX price comes to the value the reference shows at reopen.
3. **What these markets can absorb.** Pool depth below the current price, set against the collateral that
   lending markets on Base would liquidate if the reference moved down 5%, 10% or 20%.

Every published number is a measurement with its inputs. Nothing here is a verdict on any token, pool,
protocol, issuer or forecaster, and nothing here says what anyone should do in any market.

Every export is stamped with `methods_version`. A change to any definition below bumps the version.

## 1. Principles

- **Measurements, not verdicts.** Flags are booleans with a heuristic id and an evidence pointer. Tiers
  (`no_flags`, `one_flag`, `flagged`, `stale`, `insufficient_data`) count flags; they assert nothing else.
- **Replayable.** Every published file is a pure function of the raw chain logs in `data/raw/`, the
  config files in `config/` and this document. `callrec replay` regenerates an export from those inputs
  and compares it file by file. An export is as of the earliest time (whole minutes) to which every raw
  stream has been read, never later; the manifest records how far each stream was read
  (`data_read_to_ms`). Rows read later can then never change a replay. The daily export is refused when a
  stream lags the requested time by more than 2 hours.
- **Signed and anchored.** Each export's manifest is signed with the key in `keys/export-key.json`, and
  the SHA-256 of the manifest is put on the record on Base once a day (schema 3, section 4).
- **House wallets are labelled and excluded.** The project's own forecasters commit from the five
  wallets in `config/house.yaml`, on the schedule in section 7, one transaction per forecaster per window.
  No usage figure ever counts them.
- **Open probabilities are shown after resolution.** The site shows that a wallet committed to an open
  window, never its probabilities until the window has resolved. They are public on chain regardless.
- **No positions.** The operator holds no position in any measured token, pool or lending market.

## 2. Inputs

| Input | Where | How |
|---|---|---|
| Official token list | `config/tokens.json` | Coinbase Tokenized Stocks API, every page, each token checked on chain (`symbol`, `decimals`, `uiMultiplier`) |
| Reference feeds | `config/feeds.yaml` | Chainlink's feed directory for Base ("Coinbase TICKER", `us_equities_24/5`), plus three 24/7 feeds; every phase aggregator read through the proxy |
| Feed updates | `data/raw/feeds/` | every `AnswerUpdated(int256 indexed current, uint256 indexed roundId, uint256 updatedAt)` of every phase aggregator since 2026-08-24 |
| Token events | `data/raw/b20/` | multiplier, announcement, pause, policy, name, symbol and metadata events of every official token |
| Pools | `config/pools.yaml` | DEX pools trading the tokens, each verified on chain against its factory (123 pools of 46 tokens; method in docs/research/POOLS.md) |
| Swaps | `data/raw/swaps/`, `data/raw/swaps_v4/` | `Swap` logs of the pools used (below) |
| Lending markets | `config/lending.yaml` | every market on Base that accepts the tokens as collateral (Morpho Blue, Aave V4 Equities Hub; Euler v2 listed, holding none) |
| Lending positions | `data/raw/morpho/`, `data/raw/aave_v4/`, `data/raw/snapshots/lending/` | position events (who has a position) and position reads at snapshot blocks |
| Depth | `data/raw/snapshots/depth/` | pool state (price, liquidity, initialized ticks) at snapshot blocks |
| Records | `data/raw/ledger/` | every `Committed` event of the CallLedger contract |
| Offchain pages | `data/raw/offchain/index.jsonl` | URL, time, status, length and SHA-256 of a daily copy of the issuer's list and token page, the integration docs and the feed directory (copies kept private) |

**Measured tokens.** Official tokens with a Chainlink 24/5 reference feed (12 at version 0.1.0). The other
official tokens appear in the registry only.

**Pools used.** Listed pools of measured tokens that pair with USDC, on Aerodrome Slipstream (both factories),
Uniswap v3 and Uniswap v4 (45 pools at version 0.1.0; they carry about 95% of the measured tokens' listed
volume). WETH and native-ETH pairs, pairs with other tokens, and pools on factories with a different swap
event are not used yet.

**Where the swap logs live.** The swap streams hold tens of thousands of logs a day, so they are not kept in
the repository. They are re-read from the chain (`callrec ingest swaps`), and the export manifest records
the SHA-256 of every day file's uncompressed content (the rows, one JSON object per line, sorted keys, LF
endings). Serialisation is deterministic, so a re-read can be checked byte for byte on any machine; the
compressed bytes are not hashed, because they depend on the zlib build. Every other raw input is kept in the
repository.

Block times come from the block number (`config/chain.yaml` `block_time`: 2 s blocks until block 53,556,127,
200 ms blocks from 53,556,128, both checked against headers). The value of a feed at time t is the answer
of the latest `AnswerUpdated`, from any phase aggregator of that feed, whose block time is at or before t.
Round ids are never used to order or look up values.

The reference feed already includes the token's multiplier (Chainlink: token price = underlying price x
multiplier), so DEX prices of the token compare with it directly.

## 3. Windows

Times are US Eastern (America/New_York). The 24/5 session of the reference feeds runs from Sunday 20:00
to Friday 20:00; full market holidays (`config/calendar.yaml`, from the NYSE calendar) close the session
that ends at 20:00 on that day.

- **Closed window** (kind 1). A closed span runs from a session close to the next reopen: Friday 20:00 to
  Sunday 20:00, longer around a holiday, or a mid-week holiday span. Its window is dated by the Eastern
  date the span starts.
  - start: the span start (the reference value then is the frozen value);
  - cutoff: reopen minus 120 minutes;
  - end: reopen plus 60 minutes; the outcome is the reference value then.
- **Daily window** (kind 2), one per open session day d: from 20:00 on day d-1 (or from the previous
  closed window's end) to 20:00 on day d; cutoff = start.

Window id = kind x 100,000,000 + yyyymmdd. A record counts for a window only if its block time is at or
before the window's cutoff.

## 4. Records (the CallLedger contract)

`commit(uint32 windowId, uint16 schemaId, bytes data)` emits
`Committed(address indexed committer, uint32 indexed windowId, uint16 indexed schemaId, bytes data)` and
stores nothing. The contract has no owner, no admin, no storage and no payable function. Bytes after the
ABI arguments (ERC-8021 attribution suffixes) are ignored, so a caller's Builder Code rides along.

| Schema | Meaning | Encoding of `data` |
|---|---|---|
| 1 | probability calls | 26 bytes per token, sorted by address: token (20) \| p_up_bps uint16 (0 to 10,000) \| ret_bps int32 (point call, expected log return in basis points; 0x80000000 = none) |
| 2 | coverage call | snapshot block uint64, then 74 bytes per token: token (20) \| for 5%, 10%, 20%: depth_usd uint48, liquidation_flow_usd uint48, underwater_debt_usd uint48 (whole dollars; 0xFFFFFFFFFFFF = not measured) |
| 3 | daily anchor | SHA-256 of the day's export manifest (32) \| export date yyyymmdd uint32 |

`p_up_bps` is the probability, in basis points, that the reference value at the window's end is above
its value at the window's start. The first record per (committer, window, schema) is the scored one;
later records are kept and shown, never scored.

## 5. Scoring

**Slate.** A window's slate is every official token with a 24/5 reference feed that updated at least
once in the seven days before the window starts. The slate is fixed from data before the window opens.

**Outcome.** For slate token k in window W: o = 1 if ref(W.end) > ref(W.start), 0 if below. The token is
void for W, with the reason published, when:
- either value is missing (`missing_reference`);
- a token event falls inside W: a multiplier update scheduled or applied, a cancellation, an
  announcement, a pause or unpause (`token_event_in_window`);
- for a closed window, the feed has not updated after the reopen by W.end (`no_update_after_reopen`);
- for a daily window, the end value is more than 26 hours old (`stale_reference`);
- the two values are equal (`unchanged_reference`).

**Brier score.** For a forecaster that committed to W before its cutoff: (p - o)^2 per non-void slate
token, where a slate token it left out counts as p = 0.5.

**Baselines.** Computed for every window, whether or not the house committed:
- *50%*: p = 0.5 everywhere (Brier 0.25).
- *DEX-implied* (section 6): from the gap between the DEX price and the frozen or current reference.
- *Persistence* (point calls only): an expected return of 0.

**Per forecaster**, over the windows it committed to:
- `brier`: mean Brier over its scored (window, token) pairs;
- `skill_vs_dex` = 1 - brier / (DEX-implied baseline's Brier on the same pairs);
- `skill_vs_50` = 1 - brier / 0.25 (a forecaster at 50% everywhere scores exactly 0);
- `edge_lcb`: with d_w = mean over W's tokens of (baseline Brier - forecaster Brier), the one-sided 95%
  lower bound mean(d) - 1.645 x sd(d) / sqrt(n) over its n scored windows.

**Ranking.** By `edge_lcb`, for forecasters with at least 5 scored windows; the rest are listed unranked.

**What the board cannot show yet.** With a few dozen windows, skill and luck cannot be told apart. The
lower bound and the minimum count reduce, not remove, the chance that a ranking reflects luck; with many
forecasters, the best of them will look skilled by chance. The site says so next to the ranking.

**Point calls** (ret_bps given): squared error, in bps^2, of the realised log return
ln(ref(end)/ref(start)) x 10,000, reported against persistence (0) on the same pairs. Not ranked.

## 6. The weekend tape and the DEX-implied baseline

For each closed window and token, from the Swap logs of the token's listed pools:
- the DEX price path: after each swap, the pool's price in USD (USDC = 1; WETH pairs at the Chainlink
  ETH/USD value at that time);
- the time-weighted DEX price (TWAP) of the primary pool (the listed pool with the most USDC volume over
  the trailing 30 days) over [span start, cutoff], and its last-hour TWAP before the cutoff;
- `gap_bps` = ln(TWAP_last_hour / frozen reference) x 10,000;
- `reopen_bps` = ln(reference at window end / frozen reference) x 10,000;
- `tape_error_bps` = reopen_bps - gap_bps (how far the weekend market was from the reopen value);
- void when the primary pool has fewer than 5 swaps or less than $1,000 of volume in the last 12 hours
  before the cutoff (`dex_thin`), or when the last-hour price is more than 30% from the reference
  (`dex_price_outlier`: a broken or empty pool).

**DEX-implied probability.** p = Phi(gap_bps / sigma), clipped to [0.05, 0.95]. Sigma is 1.4826 x the
median absolute `tape_error_bps` over every earlier closed window (all tokens, non-void rows, windows
that ended before this window's start). That equals the standard deviation for normal errors, and one
broken pool cannot swamp it. Its floor is 25 bps, and the prior is 150 bps until 4 earlier windows exist. Its point call is
gap_bps. For daily windows the gap is taken at the cutoff, against the then-current reference, with a
separate sigma from earlier daily windows (prior 150 bps). Where the DEX baseline is void the baseline
is p = 0.5.

The three 24/7 Chainlink feeds (GOOGL, NVDA, TSLA) are shown on the tape next to the DEX price as a
second weekend value; they are not used in any score.

## 7. House forecasters and schedule

| Wallet (role) | Records | When |
|---|---|---|
| null | schema 1, p = 0.5 on every slate token | daily windows: in the 12 hours before the cutoff; closed windows: from the span start to the cutoff |
| persistence | schema 1, p = 0.5 and a point call of 0 | daily windows: in the 12 hours before the cutoff; closed windows: from the span start to the cutoff |
| dex_implied | schema 1, the DEX-implied p and point call (section 6); p = 0.5 and no point call where the DEX baseline is void | closed windows: in the 2 hours before the cutoff; daily windows: in the hour before the cutoff |
| coverage | schema 2, the coverage call (section 8) | each closed window, within 2 hours after the span start |
| anchor | schema 3, the daily export hash | once a day |

Each runs from a scheduled job, at most one transaction per role per window (the job reads the chain
first and does nothing if the record exists). The job is started at fixed times by scheduled pushes
(`config/house_ticks.yaml`), with GitHub's own schedule as a backstop: GitHub ran it 6 to 8 hours late in
the first week, so the null and persistence slots of daily windows are 12 hours wide. A Monday job reads the chain for the past closed window's
house records and publishes `house_commit_missing` (with the expected role and window) if one is absent.
House wallets never trade and never hold the measured tokens. They appear on the board, labelled, and
are excluded from every usage figure.

## 8. What these markets can absorb

**Depth** (per token, from pool state at a block, liquidity providers assumed not to move):
- `move_1pct_usd`, `move_2pct_usd`: USD paid out by the pools as the price moves down 1% / 2% from each
  pool's current price;
- impact of a token-to-USDC swap of $10,000 and $100,000 in the primary pool (before the pool fee);
- `absorb_5pct_below_usd[s]`: USD the pools pay out between ref x (1 - s) and ref x (1 - s) x 0.95, for
  s = 5%, 10%, 20%: the depth that would meet liquidation flow at a shocked price.

Concentrated-liquidity pools are walked tick by tick; constant-product pools use the closed form.

**Liquidation flow** L(s): for every borrower position in a listed lending market that uses the token as
collateral, the collateral that becomes liquidatable if the price the market's oracle reads falls by s,
valued at the shocked price, using the market's own liquidation threshold, close factor and incentive.
While the reference is frozen nothing can be liquidated; the flow arrives at the reopen, at the gap price.
- Each token is shocked alone; other prices are unchanged.
- *Morpho Blue:* liquidatable when collateral x price x LLTV < debt; no close factor; seized collateral =
  min(collateral, debt x LIF / price) with LIF = min(1.15, 1 / (1 - 0.3 x (1 - LLTV))).
- *Aave V4:* only reserves the user enabled as collateral count. Health factor = sum(collateral x price x
  collateral factor) / debt. The repaid amount restores the target health factor (1.24), or takes the
  whole debt or reserve under the $1,000 dust rules. The bonus slides with the health factor. The shocked
  reserve is liquidated first.
- Both protocols read the Chainlink 24/5 feeds without a staleness check (docs/research/LENDING.md).

**Underwater debt** U(s): the debt of positions whose collateral, at the shocked price, is worth less than
the debt.

**Coverage** = depth / L(s) is published with the dollar figures beside it. Coverage below 1.0 means the
measured depth in the 5% below the shocked price is smaller than the measured liquidation flow.

**Limits.** These measure onchain absorption only: no offchain venue, no liquidator inventory, no
liquidity added after the snapshot, no other collateral of the same borrower. A lending market whose
positions cannot be read is listed with its reported totals as unmeasured, never silently left out.

**Scoring the coverage call.** Every closed window with a house coverage record: the depth committed at
the span start, compared with the depth at the same price levels in the first snapshot taken in the two
hours after the reopen (`depth_change_pct`). When a token's reopen move is 5% or more, the committed
liquidation flow is also compared with the collateral seized by `Liquidate` (Morpho) and
`LiquidationCall` (Aave V4) events in the 24 hours after the reopen. Every miss stays on the page.

**Snapshots** are taken once a day, in each coverage slot, and in the hour after each reopen. The depth
engine was checked against Uniswap's QuoterV2 at one block and agreed to rounding
(docs/research/DEPTH-CHECK.md).

## 9. Market quality flags (per token, per day)

| Id | Boolean | Evidence |
|---|---|---|
| S1_stale_reference | the 24/5 feed's last update is older than 26 hours outside a closed span | feed update block |
| S2_dex_gap_large | the primary pool's price differs from the reference by more than 2% outside a closed span | price, block |
| R1_lookalike_symbol | a token in a listed pool's Swap logs has an official token's symbol but is not on the list | token address |
| D1_depth_thin | `move_2pct_usd` below $10,000 | depth snapshot |

Tier: `stale` if S1; else `insufficient_data` if no depth snapshot; else `no_flags` / `one_flag` /
`flagged` (two or more).

### 9b. Volume shares by heuristic (supporting numbers)

Per token, over the listed pools, since 2026-08-24 and over the last 7 days: the share of USD swap volume
carrying each boolean. No address is named.

| Id | Boolean, per swap |
|---|---|
| OV1_round_trip_10m | the same address takes both directions in the token's pools within 10 minutes (both legs) |
| OV3_sandwich_leg | in one block and pool, an address's swap, then another address's swap in the same direction, then the first address's swap in the other direction (the first address's two legs) |
| OV2_shared_funding | not measured (needs every address's funding graph); published as null |

The address of a swap is its `recipient`, a proxy; an address that receives more than 200 swaps in the
token's pools on one UTC day is treated as router-like and left out of OV1. Swaps are grouped by UTC day,
so a round trip that crosses midnight UTC is not joined.

## 10. Disclosures

- This project is entered in Base's "Stocks Maxxing" builder competition (Nov 5 to Dec 5, 2026). A
  prize, if any, is accepted as an open-competition award and will be disclosed here with its amount.
  No measured party (issuer, pool, lending protocol, forecaster) pays for anything here.
- The operator holds no position in any measured token, pool or lending market.
- Coinbase tokenized stocks are offered only to persons in eligible jurisdictions outside the United
  States. Nothing here is an offer, a solicitation or advice of any kind.

## Changelog

- 0.1.0 (2026-11-08): first version.
- 0.1.1 (2026-11-10): the manifest hashes a compressed day file's uncompressed content (manifest schema
  v2). The first re-read in CI matched no compressed file, because the gzip header records the operating
  system. An export's as_of is clamped to the data actually read: a Linux replay of the 2026-11-09 export
  gave 25 of 26 files identical, and the 26th, volume_quality.json, differed because that export was dated
  02:05 with swaps read only to 01:59. No measurement definition changed.
- 0.2.0 (2026-11-13): house schedule (section 7). Null and persistence records of daily windows may be sent
  in the 12 hours before the cutoff (was the last hour), because scheduled jobs ran hours late. Their
  content does not depend on the send time. No measurement definition changed.
