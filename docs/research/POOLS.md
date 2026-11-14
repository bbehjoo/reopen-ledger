# DEX pools for Coinbase tokenized stocks on Base (research note, 2026-11-08)

Source note for `config/pools.yaml`. A snapshot: API figures were fetched 2026-11-08 between 23:31 and 23:50 UTC,
chain reads are pinned at block 54,955,120 (23:43:19 UTC). Regenerate before relying on any number.

## Method

1. **Official list.** `GET https://api.coinbase.com/v1/tokenized-stocks` returns 100 rows and a `next_page_token`;
   the next page is `?page_token=<token>` (`pageToken` also works; the token is base64 of the page's last contract
   address). 3 pages, 298 tokens, all at `0xb200000000000000000000…` with 8 decimals. 71 rows carry `total_supply`
   and `first_mint_date`, 12 carry `nav_price`, 8 have `multiplier` other than 1. Raw pages with fetch times:
   `data/scratch/official_tokens.json` (gitignored).
2. **Discovery.** DexScreener `token-pairs/v1/base/<token>` for all 298 tokens (the endpoint returns at most 30 pairs;
   GOOGLc, NVDAc and SPCXc hit that cap). GeckoTerminal `tokens/multi` for all 298 as a first screen, then
   `tokens/<token>/pools?page=1..5` for the 47 tokens that passed either screen. Across both APIs, 1,355 distinct
   pools include an official token.
3. **Activity cutoff.** A pool is listed if its 24h volume is above $1,000 in either API, or its API liquidity is
   above $10,000 and the pair token is USDC, WETH, native ETH or another official stock token. For any other pair
   token only the volume leg counts. A token passes if one of its pools is listed. Reason for the second clause: the
   plain rule ("volume > $1,000 or liquidity > $10,000") passes 523 pools, and 400 of them have some other pair
   token (mostly launchpad tokens) and pass on liquidity alone, where the API's USD figure is priced off that token. Result: **46 of 298
   tokens pass, 123 pools listed** (the plain rule would add one token, QUBTc, through a `wUSDC / QUBTc` v4 pool
   with about $10.0k of API liquidity and $4 of volume).
4. **On-chain verification**, all at block 54,955,120 through Multicall3 on `mainnet.base.org`:
   - Pair contracts (Uniswap v3, Slipstream, Aero CL, PancakeSwap v3, Algebra-style): `factory()`, `token0()`,
     `token1()`, `fee()`, `tickSpacing()`, `slot0()` (or `globalState()`), `liquidity()`, then the factory's own
     lookup must return the pool: `getPool(t0,t1,fee)` for Uniswap v3 and PancakeSwap, `getPool(t0,t1,tickSpacing)`
     for Slipstream and Aero CL, `poolByPair(t0,t1)` for Algebra-style. All 92 pair pools pass.
   - Uniswap v4: the PoolKey (currency0, currency1, fee, tickSpacing, hooks) comes from the PoolManager `Initialize`
     log; `keccak256(abi.encode(PoolKey))` equals the poolId for all 31; then StateView `getSlot0(poolId)` and
     `getLiquidity(poolId)`.
   - `symbol()` and `decimals()` for every token in a listed pool; `spot_stock_in_pair_token` from `sqrtPriceX96`
     and decimals. For the largest USDC pools it sits within 4% of the list's `nav_price` (stamped 2026-11-06),
     which checks decimals and orientation. It is per token; 8 tokens have an API `multiplier` above 1.
5. **Creation block and tx** found for all 123 pools: factory `PoolCreated` / Algebra `Pool` / PoolManager
   `Initialize` log, located near the API creation time (drpc, 100-block windows), backward from it in 10k-block
   chunks (publicnode), or by `eth_getCode` bisection followed by a one-block log read. Each entry records its method.
6. **Event topic0** values are keccak256 of the signatures and match live logs of the NVDAc/USDC pools; the Aero
   MetaDEX03 CL pools emit the same Swap/Mint/Burn/Collect topics as Uniswap v3.
7. **Factory sources.** Uniswap v3 factory, v4 PoolManager and StateView: developers.uniswap.org deployment pages.
   Aerodrome classic PoolFactory: `aerodrome-finance/contracts` README. Slipstream factories (initial, gauge caps,
   gauges v3): `aerodrome-finance/slipstream` README. Aero MetaDEX03 clFactory and volatile/stable factories:
   `dromos-labs/metadex-slipstream-public` and `dromos-labs/metadex-public` `deployment-addresses/*-base.json`.
   PancakeSwap v3: developer.pancakeswap.finance. Hydrex: the pool deployer in `hydrexfi/hydrex-sdk` equals
   `factory.poolDeployer()`. One Algebra-style factory (`0xf4502A98…5b83`) has no public source.

## Counts and 24h volume share

Volume per pool is GeckoTerminal's where it has the pool, else DexScreener's. Liquidity is the API figure.

| protocol (factory) | pools | 24h volume USD | share | API liquidity USD | share |
|---|---:|---:|---:|---:|---:|
| aerodrome-slipstream (Aero MetaDEX03 clFactory) | 42 | 78,141,577 | 99.19% | 14,197,637 | 78.13% |
| aerodrome-slipstream (Slipstream gauges v3 factory) | 35 | 248,887 | 0.32% | 2,409,744 | 13.26% |
| uniswap-v4 | 31 | 126,674 | 0.16% | 1,234,990 | 6.80% |
| uniswap-v3 | 8 | 89,834 | 0.11% | 267,013 | 1.47% |
| other (4 unidentified Algebra-style, 2 Hydrex, 1 PancakeSwap v3) | 7 | 176,605 | 0.22% | 61,849 | 0.34% |
| aerodrome-classic | 0 | 0 | 0% | 0 | 0% |
| **total** | **123** | **78,783,576** | | **18,171,232** | |

DexScreener-only volume gives the same picture (aerodrome-slipstream 99.55%, other 0.22%, v4 0.12%, v3 0.11%).
Pair tokens: USDC 89 pools, WETH 8, native ETH 5, other 21.

Largest pools by API liquidity (all Aero MetaDEX03 CL, tick spacing 10, created 2026-10-21):
AMZNc/USDC `0x532e0F46d1e528507FC9454d5847C231f23bDDf6` $1.75M (24h $5.98M); GOOGLc/USDC
`0x16c70F04C3080a127486Cdf5a4C33c066bBF47C3` $1.71M ($3.95M); SNDKc/USDC `0x2836e062a3fe75943a7F4A552E2365b98E414E75`
$1.53M ($13.26M); METAc/USDC `0xd072410fa13D242e1d53721Bcf7AF02e3455DC96` $0.89M ($3.15M); SPCXc/USDC
`0x880dB7Dda4407D99508574E680d067D1164B3cFE` $0.75M ($8.68M); MSTRc/USDC `0x66DCd42E6314B287110922AE36cB2a8bdEECc153`
$0.69M ($12.29M); NVDAc/USDC `0xF668e21993f0ACd7ab00BB1cFbAeD0df28A3C8EC` $0.68M ($4.33M); MSTRc/cbBTC
`0x988B949de9d3A3d2172F22C19694c7a5148c9E87` $0.52M ($2.03M).

## Surprises and notes

- **Volume sits in the new Aero pools.** 39 of the 42 Aero MetaDEX03 CL pools were created on 2026-10-21 (blocks
  52,885,484–52,915,389, most between 05:25 and 05:49 UTC), 3 more on 2026-10-26. The older Slipstream
  (gauges v3) pools still hold $2.4M of API liquidity but carry 0.3% of the volume. A tape or depth measurement that
  reads only the older Aerodrome factories would miss almost all of the flow.
- **Fees move.** Aero CL `fee()` ranged from 242 to 3,587 pips across pools at the read block and differs from the fee
  printed in GeckoTerminal pool names (NVDAc/USDC: 3,587 pips on chain, "0.171%" in the name). The config records
  `fee()` at the read block only.
- **Pools older than the first mint.** 24 of the 123 pools predate their token's `first_mint_date`. Slipstream USDC
  pools for AAPLc, NVDAc, GOOGLc and METAc were created 2026-07-29 14:42–14:48 UTC (blocks 49,273,396–49,273,564),
  two weeks before the 2026-08-12 first mint; six more on 2026-08-25, nine days before theirs.
- **18 tokens have one listed pool each, all alike.** ARMc, BIDUc, BILIc, BUDc, HSAIc, INFYc, LIc, NIOc, NOKc, NVOc,
  PDDc, SANc, SAPc, SEc, SONYc, ULc, VALEc and WRDc each have one listed pool: a Slipstream USDC pool with tick
  spacing 1 and fee 100 pips, created 2026-10-09 18:26–18:58 UTC (minutes before first mint where the list gives
  one), with $41k–$65k of API liquidity and 24h volume of $0–$106, except ARMc at $29.8k.
- **Pairs other than USDC/WETH.** MSTRc/cbBTC (Aero CL) is the eighth largest pool and carries $2.03M of 24h
  volume. Seven Aero CL pools pair a stock token with frxUSD ($404–$1,164 liquidity, $1.5k–$3.7k volume each).
  Others: TSLAc/rETH, ST0x wrapped stock tokens on Hydrex (NVDAc/wtNVDA, MSTRc/wtMSTR), GOOGLc/MAG7,
  SPCXc/ElonRWA, MUc/TE, AMZNc/DGUY on Uniswap v3, and launchpad tokens on Uniswap v4 (BLUECHIP, IPOD, CLANKED,
  BB, CREHT, DiamondPepe).
- **The B20 address pattern is not unique to the list.** 210 tokens seen in the APIs have the official
  `0xb200000000000000000000` prefix and `eth_getCode` = `0xef` but are not on the official list, including the pair
  token of NVDAc's largest v4 pool (BLUECHIP, `0xB200000000000000000000cFbdF64a8706a94a01`). Identify official tokens
  by list membership, not by prefix or code.
- **Uniswap v4 hooks.** 24 of the 31 listed v4 pools have hooks and 18 set the dynamic-fee flag. One hook contract,
  `0x81f989dcB1677ccEa3A4f822aa871c08bD2400C4`, sits on 13 USDC pools created 2026-11-02 to 2026-11-06 (lpFee 400 to
  2,000 pips at the read block; with the dynamic flag a hook can set a per-swap fee, so swap logs, not slot0, give
  the fee charged). The 7 hookless v4 pools report a nonzero StateView `protocolFee` (1,000 pips each
  direction; 400 on the 0.25% GOOGLc/MAG7 pool). Five of the six launchpad-token pools set PoolKey fee 0; all six have hooks.
- **Small pools carrying volume.** CRWVc/USDC Aero CL: $40 of API liquidity, $2,252 of 24h volume. The four pools on
  the unidentified Algebra-style factory (GOOGLc, NVDAc, MSTRc, METAc against USDC, DexScreener only) hold
  $5k–$17k each and turned over $12k–$79k. NVDAc/ETH v4 `0xc5777a…`: $1.0k liquidity, $8.3k volume. Among large
  pools, MSTRc/USDC Aero CL turned over 18 times its API liquidity in 24h.
- **No Aerodrome classic pool passes.** The NVDAc/USDC classic pool holds about $0.01.
- **API timestamps.** GeckoTerminal `pool_created_at` matches the creation block for Uniswap v3, v4 and PancakeSwap
  pools, but trails the factory event for Slipstream and Aero CL pools by 15 minutes to 15 days. DexScreener gives
  no `pairCreatedAt` for any Slipstream or Aero CL pool.
- **Infrastructure limits met today.** publicnode serves logs only from about block 51,010,000 ("archive requests
  require a personal token") and accepts at most 10 addresses per filter; drpc's free tier accepted 100-block log
  ranges and refused 1,000; `mainnet.base.org` and drpc both answered historical `eth_call` and `eth_getCode`;
  GeckoTerminal returned 429 at one request every 4 seconds.

## Lookalikes

51 tokens seen in these API responses resemble an official token at another address (rules in `pools.yaml`):
10 share a symbol case-insensitively (AAPLc `0x7102…09cb`, two AMDc, CRCLc `0x5e6c…4d72`, MSTRc `0x05dd…4fbd`,
NVDAc `0x345c…5f43`, SPCXc `0x5480…84dc`, METAC, TSLAC, and AIC next to the official AIc), 8 are `wt`-prefixed ST0x
wrapped stocks, 32 use the bare ticker (for example 5 META, 5 AMD, 4 MSTR), 1 is BMSTR. 8 of the 51 sit at
B20-pattern addresses with code `0xef`. The list records what the APIs showed and nothing about the issuers.
