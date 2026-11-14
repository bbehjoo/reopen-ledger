# Lending markets on Base that accept Coinbase B20 stock tokens as collateral

Research note, 2026-11-08. Read-only: HTTP GETs, public APIs, and JSON-RPC reads (`eth_call`, `eth_getLogs`,
`eth_getCode`, `eth_blockNumber`, `eth_getBlockByNumber`; one `eth_getStorageAt` for the two proxy implementation
slots). No transaction, no signature, no wallet. The machine-readable draft is `config/lending.yaml`.

Snapshot blocks: Morpho reads at block **54,954,595** (2026-11-08 23:41:34 UTC); Aave V4 reserve reads at block
**54,953,835**; per-position reads at the blocks named in each section.

## 0. Summary

| Protocol | Stock collateral (USD at oracle price) | USDC debt against it | Readable at latest block from free RPC |
|---|---|---|---|
| Aave V4, Equities Hub / MAG7 spoke | 15,427,723 (8 reserves) | 6,723,141 | **Yes.** Reserves, configs, prices, every user's collateral, debt and health factor are `eth_call` views; users are enumerable from spoke events with publicnode `eth_getLogs` (50,000-block windows work from the spoke deployment block). |
| Morpho Blue | 105,618 (9 listed markets with any size, 7 of them above 1 USD) | 47,116 | **Yes.** Markets, oracles, positions are `eth_call` views; borrowers are enumerable from Morpho events (topic1 = market id). The Morpho API returns the same positions and matched the on-chain share totals exactly. |
| Euler v2 (EVK) | 0 backing debt | 0 | **Yes**, but nothing to measure today: 22 EVK vaults hold stock tokens (dust, about 2,300 USD in all), and only one USDC borrow vault lists a stock collateral vault (NVDAc, liquidation LTV 0.92), which holds 0. |
| Fluid, Moonwell, others | none found | none | Not listed in DefiLlama's Base pool set for any of the 298 official token addresses; no on-chain check done. |

What blocks or qualifies the shock computation:

1. **Weekend freeze.** Every market reads the Chainlink 24/5 feeds, and neither Morpho's `MorphoChainlinkOracleV2` nor
   Aave V4's `AaveOracle` checks staleness. At the snapshot the eight feeds' last updates were Friday 2026-11-06
   between 17:37 and 21:42 UTC, 50 to 54 hours before the snapshot. A shock "applied to the oracle" can only land
   when the feed next updates. These reads do not pin the exact freeze window (the reported Fri 20:00 to Sun 20:00 ET
   stays unverified): with a 0.5 % deviation trigger, the last update before the weekend need not coincide with the
   end of the session. Chainlink also publishes 24/7 variants for GOOGL, NVDA and TSLA (listed in `config/feeds.yaml`,
   built 2026-11-08 23:40 UTC) that no lending market reads; that file records the 24/7 NVDA answer at 182.735
   against the 24/5 answer of 187.966 that both protocols read (-2.78 %).
2. **Aave V4 multi-collateral positions.** A user can post several stock reserves against one USDC debt. The health
   factor, and therefore liquidatability, depends on all of them; the bonus depends on the health factor; and the
   liquidator chooses which collateral reserve to take. Section 2.6 states the exact rules; per-token attribution
   needs a stated convention (the one used here: liquidate the shocked reserve first).
3. **Per-user dynamic config in Aave V4.** The collateral factor, max bonus and fee used for a user are those of the
   `dynamicConfigKey` stored on that user's position, not the reserve's latest key. At the snapshot every reserve and
   every user was on key 0; a future config change will make this matter.
4. **Interest since last accrual.** Morpho's `market()` totals are as of the market's `lastUpdate`; borrow assets
   per position are computed from shares, and interest since `lastUpdate` is missing unless `_accrueInterest` is
   replicated with the IRM's `borrowRateView`. At these sizes the difference is cents. Aave V4's views accrue the
   hub's drawn index to the current block timestamp (`AssetLogic.getDrawnIndex`), so they need no correction.

## 1. Common inputs

### 1.1 Tokens

Official list: `https://api.coinbase.com/v1/tokenized-stocks` (three pages with `page_token=<next_page_token>`;
**298** tokens at the snapshot, all with `decimals: 8`; `multiplier` field per token). The two tokens checked
on-chain (AAPLc, NVDAc) return `eth_getCode = 0xef`, `decimals() = 8` and `uiMultiplier()` (selector `0xa60bf13d`)
in WAD. API multipliers at the snapshot: AAPLc, AMZNc, MSFTc, TSLAc, SPCXc 1.0; NVDAc 1.000538 (on-chain
1.000537939576369481); GOOGLc 1.000377; METAc 1.000314.

### 1.2 Chainlink feeds read by the lending markets

Base's B20 specification states the feed publishes **underlying price x multiplier**, i.e. the price of one token, not
one share (source: https://docs.base.org/specifications/b20/tokenized-stocks-on-base). So no multiplier correction is
needed between the oracle answer and the token amount the protocols hold. Feed parameters from the Chainlink
directory (https://reference-data-directory.vercel.app/feeds-ethereum-mainnet-base-1.json): heartbeat 86,400 s,
deviation 0.5 %, 8 decimals, market hours `us_equities_24/5`.

| Token | Feed proxy | `description()` | latestRoundData answer | updatedAt (UTC) |
|---|---|---|---|---|
| AAPLc | `0x787f13dEa48Db0897CbCDD985de77809D837F988` | Coinbase AAPL | 343.05875000 | 2026-11-06 19:58:39 |
| AMZNc | `0x06A8E4b3aBB3B7543d8396FB2B763d22820cB295` | Coinbase AMZN | 259.89500000 | 2026-11-06 20:41:36 |
| GOOGLc | `0x5bF49E0ffA937CE2FfF033c739aD7C634c4D34F2` | Coinbase GOOGL | 285.66383855 | 2026-11-06 17:37:48 |
| METAc | `0x6526aE6797A76123638b863AeE4dD27Ba4E4b27D` | Coinbase META | 612.54015008 | 2026-11-06 20:54:02 |
| MSFTc | `0xeB10A6c9aa7E537aEd766C08c35Dae35B321b18c` | Coinbase MSFT | 531.98005000 | 2026-11-06 19:55:26 |
| NVDAc | `0x04689a41629776563E6822F76f2e57D148d28513` | Coinbase NVDA | 187.96606001 | 2026-11-06 21:39:16 |
| TSLAc | `0xFaf869185383a24F8cb00e27BdA6b63B9905DCb4` | Coinbase TSLA | 359.09000000 | 2026-11-06 21:42:54 |
| SPCXc | `0x6A634B235903C4ad6376892180d6fF8612e3Fa68` | Coinbase SPCX | 135.31975000 | 2026-11-06 21:04:38 |
| USDC (Aave V4 debt) | `0xC7d0f8dCC1F860ca752054c59Ea82Ba2A5AaB50c` | (not read) | 0.99976765 via `AaveOracle` | (not read) |

Selectors: `latestRoundData()` `0xfeaf968c`, `latestAnswer()` `0x50d25bcd`, `decimals()` `0x313ce567`,
`description()` `0x7284e416`, `aggregator()` `0x245a7bfc`.

Shocking "the oracle each market reads" therefore means shocking these eight feed answers: Morpho multiplies the
answer by a constant, Aave V4 uses it as is, and the Aave V4 debt side (USDC) uses its own feed, which the shock
leaves unchanged.

## 2. Aave V4 (Equities Hub, MAG7 spoke)

### 2.1 Addresses

Source for every address: aave-dao address book, `src/AaveV4Base.sol` at commit `5ae5e47`
(https://github.com/aave-dao/aave-address-book/blob/5ae5e47f5d2bb88e0282ba68329eeea312bd6554/src/AaveV4Base.sol),
each line of which links the Basescan page (`https://basescan.org/address/<addr>`). The address book pins
`aave/aave-v4` at commit `2524fe4` (`lib/aave-v4` submodule); the code read for this note is
https://github.com/aave/aave-v4/tree/2524fe4018a42750300e114f2a8c4355df62a878/src.

| Role | Address | Check done |
|---|---|---|
| EQUITIES_HUB (the only hub) | `0xa4d5947Eb727A052bae69C593FfC84247EC9864E` | proxy, 1,419 bytes; EIP-1967 implementation `0xf912a34a97e78eb2b68c602701aaf06226e0d2f6` |
| MAG7_SPOKE (the spoke that lists the stocks) | `0x17905Db0e4A3514467539956c084180616AE7B8D` | proxy, implementation `0x81a73c282faa932de3b2541cee19549f4bf13b19`; first block with code **51,478,830** (2026-09-18 15:56:47 UTC, by `eth_getCode` bisection) |
| MAG7_SPOKE_ORACLE (`AaveOracle`) | `0xaBaf048fD7675Ea34a84332371ffd5D55E322A47` | `Spoke.ORACLE()` returns it; `decimals() = 8` |
| LIQUIDATION_LOGIC (external library) | `0x88dF535473C5adf1f57789734A05E555F7Deb8DB` | `Spoke.getLiquidationLogic()` returns it |
| EQUITIES_USDC_TOKENIZATION_SPOKE (ERC-4626 USDC supply wrapper) | `0x7081CE7EB1282c53CF38EA9B622f6269cb8FeFDc` | not read |
| TREASURY_SPOKE | `0x5F8d0102F5B51Fae6DE9d2F2561bda63Fb5Db674` | not read |
| Position managers (giver / taker / config), gateways | see address book | not read |
| Aave v3 Base Pool (for contrast; no stock reserves) | `0xA238Dd80C259a72e81d7e4664a9801593F98d1c5` | per the task brief |

Press: launch 2026-09-25 (https://theblock.co/news/defi/2026-09-25-aave-v4-on-base-adds-coinbase-tokenized-stocks-as-collateral-for-usdc-loans-416372).
The press lists seven stocks; on-chain there are **eight** collateral reserves (SPCXc is reserve 8).

### 2.2 How reserves are listed

A spoke holds reserves `0 .. getReserveCount()-1`. Each reserve points at `(hub, assetId)`; `getReserve(id)` returns
`(underlying, hub, assetId, decimals, collateralRisk, flags, dynamicConfigKey)`. Risk parameters live in
`getDynamicReserveConfig(reserveId, key)` as `(collateralFactor bps, maxLiquidationBonus bps, liquidationFee bps)`.
Each user position stores the key in force at its last update. Price: `AaveOracle.getReserveSource(reserveId)` is
the Chainlink proxy; `getReservePrice(reserveId)` returns `source.latestAnswer()` (requires > 0; no staleness check).

Real read, block 54,953,835 (`getReserveCount() = 9`, all reserves on hub `0xa4d5...864E`, all `dynamicConfigKey = 0`,
none paused or frozen):

| id | token | CF | max bonus | liq. fee | collateralRisk | price source | supplied (tokens) | supplied USD | debt |
|---|---|---|---|---|---|---|---|---|---|
| 0 | AAPLc | 0.78 | 1.055 | 10 % | 0 | `0x787f...F988` | 2,327.50777799 | 798,472 | 0 |
| 1 | AMZNc | 0.73 | 1.055 | 10 % | 0 | `0x06A8...B295` | 1,954.29042387 | 507,910 | 0 |
| 2 | GOOGLc | 0.76 | 1.055 | 10 % | 0 | `0x5bF4...34F2` | 19,326.72382223 | 5,520,946 | 0 |
| 3 | METAc | 0.65 | 1.055 | 10 % | 0 | `0x6526...b27D` | 5,175.94597839 | 3,170,475 | 0 |
| 4 | MSFTc | 0.79 | 1.055 | 10 % | 0 | `0xeB10...b18c` | 639.44116930 | 340,170 | 0 |
| 5 | NVDAc | 0.70 | 1.055 | 10 % | 0 | `0x0468...8513` | 16,219.70479020 | 3,048,754 | 0 |
| 6 | TSLAc | 0.65 | 1.055 | 10 % | 0 | `0xFaf8...DCb4` | 2,971.58317675 | 1,067,066 | 0 |
| 7 | USDC (borrowable, CF 0) | 0 | 1.000 | 0 | 0 | `0xC7d0...B50c` | 7,758,864.530639 | 7,757,062 | **6,723,141.110450** |
| 8 | SPCXc | 0.55 | 1.065 | 10 % | 1000 bps | `0x6A63...Fa68` | 7,197.24764677 | 973,930 | 0 |

Stock collateral supplied on the spoke: **15,427,723 USD**. Spoke liquidation config (`getLiquidationConfig()`):
`targetHealthFactor = 1.24e18`, `healthFactorForMaxBonus = 0.90e18`, `liquidationBonusFactor = 9000` (90 %).
`collateralRisk` drives the borrower's interest premium, not liquidation.

### 2.3 View functions (Spoke unless noted)

| Function | Selector | Returns |
|---|---|---|
| `getReserveCount()` | `0x99806546` | uint256 |
| `getReserve(uint256)` | `0x77778db3` | `(address underlying, address hub, uint16 assetId, uint8 decimals, uint24 collateralRisk, uint8 flags, uint32 dynamicConfigKey)` |
| `getReserveConfig(uint256)` | `0x008754a2` | `(uint24 collateralRisk, bool paused, bool frozen, bool borrowable, bool receiveSharesEnabled)` |
| `getDynamicReserveConfig(uint256,uint32)` | `0xec17bb00` | `(uint16 collateralFactor, uint32 maxLiquidationBonus, uint16 liquidationFee)` |
| `getLiquidationConfig()` | `0xe0fd5c5c` | `(uint128 targetHealthFactor, uint64 healthFactorForMaxBonus, uint16 liquidationBonusFactor)` |
| `getReserveSuppliedAssets(uint256)` | `0x2fd00527` | uint256 |
| `getReserveTotalDebt(uint256)` | `0x1cdc762c` | uint256 (drawn + premium) |
| `getReserveDebt(uint256)` | `0x93eff7a8` | `(drawn, premium)` |
| `getUserAccountData(address)` | `0xbf92857c` | `(riskPremium, avgCollateralFactor WAD, healthFactor WAD, totalCollateralValue, totalDebtValueRay, activeCollateralCount, borrowCount)`; values in USD x 1e26 |
| `getUserReserveStatus(uint256,address)` | `0xa2a522f1` | `(bool usingAsCollateral, bool borrowing)` |
| `getUserSuppliedAssets(uint256,address)` | `0xf1568a89` | uint256 token units |
| `getUserTotalDebt(uint256,address)` | `0x9b7172a6` | uint256 (drawn + premium) |
| `getUserDebt(uint256,address)` | `0x7445fb16` | `(drawn, premium)` |
| `getUserPosition(uint256,address)` | `0x869da9db` | `(uint120 drawnShares, uint120 premiumShares, int200 premiumOffsetRay, uint120 suppliedShares, uint32 dynamicConfigKey)` |
| `getLiquidationBonus(uint256,address,uint256)` | `0x46fbf741` | bonus bps for (reserve, user, health factor) |
| `ORACLE()` | `0x38013f02` | address |
| `getLiquidationLogic()` | `0x911a3413` | address |
| AaveOracle `getReservePrice(uint256)` | `0xd45c35ff` | uint256, 8 decimals |
| AaveOracle `getReserveSource(uint256)` | `0xe4337e38` | address |
| LiquidationLogic `calculateLiquidationBonus(uint256,uint256,uint256,uint256)` | `0x729f2240` | public pure; callable with `eth_call` |

### 2.4 Events for enumerating users (emitted by the spoke)

| Event | topic0 | Indexed (topic1, topic2, topic3) | Data |
|---|---|---|---|
| `Supply(uint256 reserveId, address caller, address user, uint256 suppliedShares, uint256 suppliedAmount)` | `0xd986db228cb1fe8392c5f45ff5f2c639b7db6cbd9ca7d1fe70b2de90c2c8c961` | reserveId, caller, **user** | shares, amount |
| `Withdraw(uint256,address,address,uint256,uint256)` | `0xfe7813e2866053d5c3938554e517b554fce6666a6561bed9eaa7419b29fa9b68` | reserveId, caller, **user** | shares, amount |
| `Borrow(uint256,address,address,uint256,uint256)` | `0xef18174796a5d2f91d51dc5e907a4d7867bbd6e800f6225168e0453d581d0dcd` | reserveId, caller, **user** | drawnShares, drawnAmount |
| `Repay(uint256,address,address,uint256,uint256,(int256,int256,uint256))` | `0xd765a0263e8a360da8dd4fdb8c0dc5553adec12a96f29a462cdb45e5bea407dd` | reserveId, caller, **user** | drawnShares, totalAmountRepaid, premiumDelta |
| `LiquidationCall(uint256,uint256,address,address,bool,uint256,uint256,(int256,int256,uint256),uint256,uint256,uint256)` | `0x2a1f12d996f530f89d8038aa293f9fde81cac44b6dfd6225e3358d09b78a4a37` | collateralReserveId, debtReserveId, **user** | liquidator, receiveShares, debtAmountRestored, drawnSharesLiquidated, premiumDelta, collateralAmountRemoved, collateralSharesLiquidated, collateralSharesToLiquidator |
| `SetUsingAsCollateral(uint256,address,address,bool)` | `0x4763df430bc5274807f8ab4ce0734e7898513638418d6eec0c5285ef85f7f51f` | reserveId, caller, **user** | bool |
| `ReportDeficit(uint256,address,uint256,(int256,int256,uint256))` | `0x59932f333b3a5e3fec86e662babe8dd767529ed207420e7468bd220cdfb3f076` | reserveId, **user** | drawnShares, premiumDelta |
| `AddReserve(uint256,uint256,address)` | `0xb2d3221c3db1eb0d586556ae23399acdfe3e52ff0fcd184c19069c730f9ca2e9` | reserveId, assetId, hub | |
| `UpdateDynamicReserveConfig(uint256,uint32,(uint16,uint32,uint16))` | `0x2d4f2760aaff0dfa53526a8fdd306864689a7d5e43f44ddfeece0f38315c298d` | reserveId, key | config |
| `AddDynamicReserveConfig(uint256,uint32,(uint16,uint32,uint16))` | `0xfcede5501ba87e3766118ae6ed360a87ee9b6570156ae9cac52d35ff0de0403b` | reserveId, key | config |
| `UpdateLiquidationConfig((uint128,uint64,uint16))` | `0x9062eec1933c38394d82dc926d7ddcd777a5cd08e1ae6baa94e90047338d3459` | | config |
| `UpdateReservePriceSource(uint256,address)` | `0x18a45d070f507b6387b78837652d7468e733927acc7f9a13d9cc308675735c08` | reserveId, source | |

`user` is the owner of the position (the `onBehalfOf`), also when a position manager acts. Enumerate: union of topic3
of `Supply`, `Borrow`, `SetUsingAsCollateral` and `LiquidationCall`, **plus the `liquidator` (data word 0) of every
`LiquidationCall` with `receiveShares = true`**, because such a liquidation credits collateral shares to the
liquidator without a `Supply` event; from block 51,478,830; then read each address at the latest block. For the
shock, only addresses with `borrowCount > 0` matter.

### 2.5 Real read of user positions

1. **Logs.** `eth_getLogs` on publicnode, `address = MAG7_SPOKE`, `topics = [[Supply, Withdraw, Borrow, Repay,
   LiquidationCall, SetUsingAsCollateral, ReportDeficit]]`, blocks 51,478,830 to 54,957,922 in 70 windows of 50,000
   blocks. Result: 14,768 logs (Supply 5,610; Borrow 3,015; Withdraw 2,580; Repay 2,068; SetUsingAsCollateral 1,472;
   LiquidationCall 23; ReportDeficit 0).
2. **User set.** 1,082 distinct position owners (topic3, or topic2 for `ReportDeficit`) plus the 5 distinct
   liquidators found in `LiquidationCall` data (word 0), because one of the 23 liquidations used
   `receiveShares = true` and credited collateral shares to the liquidator: 1,087 addresses.
3. **Reads at block 54,962,149** through Multicall3: `getUserAccountData(user)` and
   `getUserSuppliedAssets(r, user)` for every address and reserve; for the 292 addresses with `borrowCount > 0`,
   also `getUserReserveStatus`, `getUserPosition` (for `dynamicConfigKey`) per reserve and `getUserTotalDebt(7, user)`.
4. **Reconciliation against the reserve totals at the same block:**

| Reserve | sum of `getUserSuppliedAssets` | `getReserveSuppliedAssets` | difference (raw units) |
|---|---|---|---|
| 0 AAPLc | 232,750,777,799 | 232,750,777,799 | 0 |
| 1 AMZNc | 195,429,042,387 | 195,429,042,387 | 0 |
| 2 GOOGLc | 1,932,672,382,223 | 1,932,672,382,223 | 0 |
| 3 METAc | 517,594,597,839 | 517,594,597,839 | 0 |
| 4 MSFTc | 63,944,116,930 | 63,944,116,930 | 0 |
| 5 NVDAc | 1,621,870,479,020 | 1,621,870,479,020 | 0 |
| 6 TSLAc | 297,158,317,675 | 297,158,317,675 | 0 (96,184 before the liquidator was added) |
| 8 SPCXc | 719,724,764,677 | 719,724,764,677 | 0 |
| 7 USDC supplied | 7,638,867,170,634 | 7,638,867,170,757 | 123 (0.000123 USDC, per-user round-down) |
| 7 USDC debt | 6,723,055,983,794 (sum of `getUserTotalDebt`) | 6,723,055,983,647 (`getReserveTotalDebt`) | -147 (per-user round-up) |

5. **What the positions look like.** 292 borrowers, all with USDC debt; every borrower position read had
   `dynamicConfigKey = 0`. Collateral reserves enabled per borrower: one 169, two 35, three 25, four 21, five 7, six 7,
   seven 21, eight 7. Health factors (`getUserAccountData`): 1 below 1.00 (HF 0.9922, 1.81 USD collateral, 1.33 USD
   debt), 17 below 1.10, 41 below 1.20. Largest debts: 1,442,650 USDC (HF 1.852, seven collateral reserves),
   921,864 (HF 1.400, GOOGLc only), 646,699 (HF 1.398, NVDAc only), 602,249 (HF 1.174, GOOGLc only), 424,770
   (HF 1.393, METAc only). Health factors rebuilt from the per-reserve reads with the 2.6 formula (collateral from
   `getUserSuppliedAssets`, prices from `getReservePrice`, CF from key 0, debt from `totalDebtValueRay`) agree with
   `getUserAccountData.healthFactor` to better than 1e-6 relative for all 292 borrowers. (Using
   `getUserTotalDebt`, which rounds up to a whole raw USDC unit, instead of `totalDebtValueRay` moves dust positions
   by up to 33 %.)

### 2.6 Liquidation math (from `LiquidationLogic.sol` at `2524fe4`; constants confirmed on the deployed library)

Notation per user: `A_i` supplied amount of collateral reserve i, `p_i` its oracle price, `CF_i` the collateral factor of
the user's dynamic key, `D` total debt (drawn + premium) in USDC, `p_u` USDC price; values in USD.

* Collateral counted: reserves with `usingAsCollateral`, `CF_i > 0`, `A_i > 0`.
* Health factor: `HF = sum_i(A_i * p_i * CF_i) / (D * p_u)`. Liquidatable when `HF < 1` (`HEALTH_FACTOR_LIQUIDATION_THRESHOLD = 1e18`, read from the library).
* Liquidation bonus for collateral reserve k (`maxLB_k` from the user's key; `HFmax = 0.90`, `f = 0.90`):
  * `LB = maxLB_k` if `HF <= HFmax`;
  * otherwise `minLB = 1 + f * (maxLB_k - 1)` and `LB = minLB + (maxLB_k - minLB) * (1 - HF) / (1 - HFmax)`.
  * Deployed check: `calculateLiquidationBonus(0.9e18, 9000, hf, 10550)` returned 10500 at HF 0.99, 10522 at 0.95, 10550 at 0.90 and 0.50.
  * For the 1.055 reserves the bonus runs from 1.0495 (HF just below 1) to 1.055; for SPCXc (1.065) from 1.0585 to 1.065.
* No fixed close factor. Debt repaid in one call (value) is the smallest of `debtToCover`, the user's debt, and the
  amount that restores the target health factor `THF = 1.24`:
  `R_target = D * p_u * (THF - HF) / (THF - LB * CF_k)`
  (from `_calculateDebtToTargetHealthFactor`; the denominator is positive by a config invariant `LB * CF < 1`).
* Collateral removed from reserve k: `S_k = R * LB / p_k` (token units), capped at `A_k`; if capped, `R = A_k * p_k / LB`.
* Dust rules (`DUST_LIQUIDATION_THRESHOLD = 1000e26`, i.e. 1,000 USD, read from the library): if the remaining debt
  value would be below 1,000 USD the whole debt is taken; if the remaining collateral in reserve k would be below
  1,000 USD the whole reserve k is taken (the target health factor is bypassed in both cases).
* Liquidator receives `S_k - S_k * fee * (LB - 1) / LB` (fee 10 % of the bonus part goes to the protocol).
* Deficit: if the liquidated collateral was the user's last active collateral and debt remains, the remaining debt
  is reported as deficit (`ReportDeficit`).
* Underwater test for the measurement: `sum_i(A_i * p_i) < D * p_u` (all enabled collateral, before factors).

### 2.7 Feasibility

Readable at latest block from free RPC: **yes**, because every quantity in 2.6 is an `eth_call` view on the spoke,
oracle or library (batched through Multicall3 `0xcA11bde05977b3631167028862bE2a173976CA11`, `aggregate3` `0x82ad56cb`)
and the user set is enumerable from spoke events with publicnode `eth_getLogs` from block 51,478,830.

## 3. Morpho Blue

### 3.1 Addresses

* Morpho Blue singleton `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` (code present; source:
  https://docs.morpho.org/get-started/resources/addresses/). `MorphoChainlinkOracleV2Factory`
  `0x2DC205F24BCb6B311E5cdf0745B0741648Aebd3d`; AdaptiveCurveIrm `0x46415998764C29aB2a25CbeA6254146D50D22687` (same page).
* Code: https://github.com/morpho-org/morpho-blue/tree/bc479b91828f697d88a8cd6adaee4e6992b80ec6/src
* Market discovery: Morpho API `https://api.morpho.org/graphql`, query `markets(where: {chainId_in: [8453],
  collateralAssetAddress_in: [...]})`; the filter accepts at most **100** addresses, so the 298 tokens go in three
  chunks. Other filter names that exist: `uniqueKey_in`, `oracleAddress_in`, `loanAssetAddress_in`, `listed`,
  `search`. Positions: `marketPositions(where: {marketUniqueKey_in, chainId_in})`.

### 3.2 Markets with an official stock token as collateral

The API returned **20** markets, all with USDC (`0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`) as loan token and the
AdaptiveCurveIrm. Totals below are on-chain `market(id)` at block 54,954,595; collateral from the API state (it
matched the sum of on-chain positions, 3.4); USD at the oracle price.

| Market id | Collateral | LLTV | LIF | Oracle | Oracle reads | Created | Collateral (tokens) | Collateral USD | Borrow USDC | Supply USDC |
|---|---|---|---|---|---|---|---|---|---|---|
| `0xae1a3048...3c28` | AAPLc | 0.625 | 1.12676 | `0xEcC5c9bf18CB2CfC94C2f7EFf8BDd5837A60AB0e` | BASE_FEED_1 AAPL | 51,002,661 | 101.38141628 | 34,779.78 | 14,741.72 | 16,333.39 |
| `0xb4b42dd6...3d13` | NVDAc | 0.625 | 1.12676 | `0x4F698C04d01d9CebCDd9494c189aBdD6C5453f84` | BASE_FEED_1 NVDA | 51,002,643 | 129.89327927 | 24,415.53 | 11,522.93 | 12,653.25 |
| `0x44b343b5...7ca5` | METAc | 0.625 | 1.12676 | `0x4752B27dFc1931eb9a5DFEFC7FBC9d0af9020dC7` | BASE_FEED_1 META | 51,002,679 | 36.28954785 | 22,228.81 | 10,943.33 | 11,799.94 |
| `0xce983b9e...ecf6` | SPCXc | 0.625 | 1.12676 | `0x9079857a2b5FFfC3d87052b11b866a185B4A6483` | BASE_FEED_1 SPCX | 51,002,618 | 94.50456791 | 12,788.33 | 5,180.94 | 5,747.74 |
| `0xa3913d89...84cc` | GOOGLc | 0.77 | 1.07411 | `0x24DC11055aa5b2C5692E4B77d7285c4f0fd9Cf99` | BASE_FEED_1 GOOGL | 51,002,696 | 39.36923432 | 11,246.37 | 4,676.80 | 5,263.38 |
| `0xcca091ad...2dcd42` | AMZNc | 0.625 | 1.12676 | `0x52cE337EC871EC8f3490285b70A42aAb07814769` | BASE_FEED_1 AMZN | 51,573,522 | 0.29059091 | 75.52 | 25.07 | 27.12 |
| `0x4f9329a8...7318` | MSFTc | 0.625 | 1.12676 | `0x5a4CEB3240d50A16a8BBBBc0F72C53018B8E38be` | BASE_FEED_1 MSFT | 51,573,514 | 0.13972026 | 74.33 | 25.07 | 26.70 |
| `0xc819df16...d5d5` | TSLAc | 0.625 | 1.12676 | `0xFDD26bC94502a281f333e9593501d9A3C5a9905c` | BASE_FEED_1 TSLA | 51,573,518 | 0.00109748 | 0.39 | 0.00 | 0.00 |
| `0x0cc78b1f...62a5` | GOOGLc | 0.625 | 1.12676 | `0x24DC11055aa5b2C5692E4B77d7285c4f0fd9Cf99` | BASE_FEED_1 GOOGL | 51,573,510 | 0.00114261 | 0.33 | 0.00 | 0.00 |
| `0x91360eea...612a` (unlisted) | NVDAc | 0.77 | 1.07411 | `0xE0AE3137a30393410B595E1C1d572a1449A969ea` | not a ChainlinkOracleV2; feed getters revert; `price()` = 188.0097 USD | 51,016,554 | 0.04405328 | 8.28 | 0.01 | 98.00 |
| 10 further unlisted markets | | | | | | | 0 to 0.0017 | below 0.35 | 0 to 0.15 | 0 to 3 |

The 10 further unlisted markets (full ids in `config/lending.yaml`): GOOGLc `0x4e8fcfab` (0.625), SPCXc `0xcf7cced1`
(0.625), METAc `0xcce338a2` (0.625), NVDAc `0xaba747cd` (0.625), AAPLc `0x26d61964` (0.625) all read the same 24/5
feeds; NVDAc `0xfef5641f` (0.77, 0.15 USDC borrowed) and NVDAc `0x5c800e86` (0.77) and AAPLc `0xb50ecaba` (0.625) have
oracles whose `price()` **reverts** (no liquidation possible while that holds); METAc `0xa8835b56` (0.86) has a
non-standard oracle answering 541.13 USD; AAPLc `0x560a19b8` (0.98) has a feedless ChainlinkOracleV2 with a constant
price of 1 USDC per AAPLc.

Totals over all 20: collateral **105,618 USD**, borrow **47,116 USDC**. Every listed oracle is a
`MorphoChainlinkOracleV2` with only `BASE_FEED_1` set and `SCALE_FACTOR = 1e26`
(`= 10^(36 + 6 - 8 - 8)`), so `price() = answer * 1e26`: the USDC value of one raw collateral unit, scaled 1e36. No
quote feed: USDC is taken as 1 USD. No `BASE_VAULT`. No staleness check (`price()` uses `latestRoundData().answer`).

Selectors on the oracle: `price()` `0xa035b1fe`, `BASE_FEED_1()` `0xf50a4718`, `BASE_FEED_2()` `0xdc53858c`,
`QUOTE_FEED_1()` `0x56095e11`, `QUOTE_FEED_2()` `0xacfbd39e`, `SCALE_FACTOR()` `0xce4b5bbe`, `BASE_VAULT()` `0xeaa2d7b4`,
`QUOTE_VAULT()` `0x2e6f20a6`.

Pre-liquidation: the Morpho API reports `preLiquidations.countTotal = 0` for all 20 markets. Pre-liquidation contracts
are opt-in per borrower (via `setAuthorization`), so a borrower-level check would scan `SetAuthorization`
(`0xd5e969f01efe921d3f766bdebad25f0a05e3f237311f56482bf132d0326309c0`) for pre-liquidation contract addresses; not
done here.

### 3.3 View functions and events

| Function | Selector | Returns |
|---|---|---|
| `position(bytes32 id, address user)` | `0x93c52062` | `(uint256 supplyShares, uint128 borrowShares, uint128 collateral)` |
| `market(bytes32 id)` | `0x5c60e39a` | `(uint128 totalSupplyAssets, uint128 totalSupplyShares, uint128 totalBorrowAssets, uint128 totalBorrowShares, uint128 lastUpdate, uint128 fee)` |
| `idToMarketParams(bytes32 id)` | `0x2c3c9157` | `(address loanToken, address collateralToken, address oracle, address irm, uint256 lltv)` |
| `liquidate((address,address,address,address,uint256),address,uint256,uint256,bytes)` | `0xd8eabcb8` | (state-changing; listed for reference) |
| `accrueInterest((address,address,address,address,uint256))` | `0x151c1ade` | (state-changing) |

| Event | topic0 | Indexed (topic1, topic2, topic3) | Position owner |
|---|---|---|---|
| `SupplyCollateral(bytes32 id, address caller, address onBehalf, uint256 assets)` | `0xa3b9472a1399e17e123f3c2e6586c23e504184d504de59cdaa2b375e880c6184` | id, caller, onBehalf | topic3 |
| `WithdrawCollateral(bytes32 id, address caller, address onBehalf, address receiver, uint256 assets)` | `0xe80ebd7cc9223d7382aab2e0d1d6155c65651f83d53c8b9b06901d167e321142` | id, onBehalf, receiver (caller in data) | topic2 |
| `Borrow(bytes32 id, address caller, address onBehalf, address receiver, uint256 assets, uint256 shares)` | `0x570954540bed6b1304a87dfe815a5eda4a648f7097a16240dcd85c9b5fd42a43` | id, onBehalf, receiver (caller in data) | topic2 |
| `Repay(bytes32 id, address caller, address onBehalf, uint256 assets, uint256 shares)` | `0x52acb05cebbd3cd39715469f22afbf5a17496295ef3bc9bb5944056c63ccaa09` | id, caller, onBehalf | topic3 |
| `Liquidate(bytes32 id, address caller, address borrower, uint256 repaidAssets, uint256 repaidShares, uint256 seizedAssets, uint256 badDebtAssets, uint256 badDebtShares)` | `0xa4946ede45d0c6f06a0f5ce92c9ad3b4751452d2fe0e25010783bcab57a67e41` | id, caller, borrower | topic3 |
| `CreateMarket(bytes32 id, (address,address,address,address,uint256) marketParams)` | `0xac4b2400f169220b0c0afdde7a0b32e775ba727ea1cb30b35f935cdaab8683ac` | id | |
| `AccrueInterest(bytes32 id, uint256 prevBorrowRate, uint256 interest, uint256 feeShares)` | `0x9d9bd501d0657d7dfe415f779a620a62b78bc508ddc0891fbbd8b7ac0f8fce87` | id | |

(Indexing per `src/libraries/EventsLib.sol`. Note the asymmetry: `WithdrawCollateral` and `Borrow` put `onBehalf` in
topic2 because `caller` is not indexed.) One `eth_getLogs` filter covers all stock markets:
`{address: Morpho, topics: [[the five topic0s], [the 20 market ids]]}`.

### 3.4 Real read: borrower enumeration and reconciliation

1. **Logs.** `eth_getLogs` on publicnode, `address = Morpho`, `topics = [[SupplyCollateral, WithdrawCollateral,
   Borrow, Repay, Liquidate, CreateMarket], [the 20 market ids]]`, blocks 51,002,618 to 54,956,127 in 80 windows of
   50,000 blocks. Result: 1,782 logs, including 18 `CreateMarket` logs whose blocks equal the API's
   `creationBlockNumber` for the 18 markets created inside the range. The two markets created earlier
   (`0xa8835b56` at 50,182,178, `0xfef5641f` at 50,987,467) could not be scanned before 51,002,618 on free RPC (see
   3.6); their positions come from the Morpho API.
2. **Owners** per the "Position owner" column of 3.3, then `position(id, owner)` for each through Multicall3 at
   block **54,960,600**, and `market(id)` at the same block.
3. **Reconciliation** (sum over owners of `borrowShares` against `market(id).totalBorrowShares`, same block):

| Market | Addresses seen | Borrowers | sum borrowShares | `totalBorrowShares` | Match | sum collateral (raw) | Events (SC / WC / B / R / L) |
|---|---|---|---|---|---|---|---|
| AAPLc `0xae1a3048` | 51 | 16 | 14,588,229,262,736,813 | 14,588,229,262,736,813 | yes | 10,138,141,628 | 131 / 93 / 113 / 90 / 0 |
| NVDAc `0xb4b42dd6` | 31 | 15 | 11,413,912,889,322,592 | 11,413,912,889,322,592 | yes | 12,989,327,927 | 132 / 73 / 130 / 81 / 3 |
| METAc `0x44b343b5` | 18 | 8 | 10,854,160,926,398,666 | 10,854,160,926,398,666 | yes | 3,628,954,785 | 80 / 54 / 73 / 50 / 0 |
| SPCXc `0xce983b9e` | 19 | 8 | 5,138,383,443,703,114 | 5,138,383,443,703,114 | yes | 9,450,456,791 | 66 / 46 / 60 / 45 / 1 |
| GOOGLc `0xa3913d89` | 24 | 11 | 4,628,298,207,383,331 | 4,628,298,207,383,331 | yes | 3,936,923,432 | 103 / 68 / 109 / 86 / 0 |
| AMZNc `0xcca091ad` | 2 | 2 | 24,925,537,283,703 | 24,925,537,283,703 | yes | 29,059,091 | 3 / 0 / 2 / 0 / 0 |
| MSFTc `0x4f9329a8` | 2 | 2 | 24,925,537,283,703 | 24,925,537,283,703 | yes | 13,972,026 | 3 / 0 / 2 / 0 / 0 |
| TSLAc `0xc819df16` | 2 | 1 | 990,000,000 | 990,000,000 | yes | 109,748 | 3 / 2 / 3 / 2 / 0 |
| GOOGLc `0x0cc78b1f` | 1 | 1 | 990,000,000 | 990,000,000 | yes | 114,261 | 1 / 0 / 1 / 0 / 0 |
| NVDAc `0x91360eea` | 3 | 1 | 10,657,537,880 | 10,657,537,880 | yes | 4,405,328 | 4 / 3 / 4 / 3 / 1 |
| AAPLc `0x26d61964`, NVDAc `0x5c800e86` | 4, 1 | 0 | 0 | 0 | yes | 0 | |

   The collateral sums equal the Morpho API's `state.collateralAssets`, and an independent pull of the API's
   `marketPositions` (263 rows for the 20 markets) gives the same borrower counts and the same share sums, including
   `0xfef5641f` (1 borrower, 150,000,000,000 shares = `totalBorrowShares`).
4. **Past liquidations** found in the same logs (5, none with bad debt): NVDAc `0xb4b42dd6` at blocks 53,288,956
   (5.87 USDC repaid, 0.0320 NVDAc seized), 53,293,999 (7.47 / 0.0412), 53,552,280 (13.04 / 0.0802); SPCXc
   `0xce983b9e` at 53,503,574 (542.50 USDC repaid, 4.6703 SPCXc seized); NVDAc `0x91360eea` at 53,297,931
   (0.99 / 0.0053).

### 3.5 Liquidation math (from `src/Morpho.sol` and `src/libraries/ConstantsLib.sol` at `bc479b9`)

Per position: `C` collateral (raw units), `P` = `oracle.price()` (1e36-scaled), borrow assets
`D = ceil(borrowShares * (totalBorrowAssets + 1) / (totalBorrowShares + 1e6))` (`toAssetsUp`, `VIRTUAL_ASSETS = 1`,
`VIRTUAL_SHARES = 1e6`).

* Liquidatable when `floor(floor(C * P / 1e36) * LLTV / 1e18) < D` (`_isHealthy`).
* Liquidation incentive factor: `LIF = min(1.15, 1 / (1 - 0.3 * (1 - LLTV)))` with `LIQUIDATION_CURSOR = 0.3e18`,
  `MAX_LIQUIDATION_INCENTIVE_FACTOR = 1.15e18` (both verified in `ConstantsLib.sol`). LLTV 0.625 gives 1.126761;
  0.77 gives 1.074114; 0.86 gives 1.043841; 0.98 gives 1.006036.
* **No close factor.** Once unhealthy, a liquidator may seize any amount up to the whole collateral in one call:
  `seizedAssets` given, `repaidShares = toSharesUp(ceil(seized * P / 1e36) / LIF)`; or `repaidShares` given,
  `seized = floor(toAssetsDown(repaidShares) * LIF * 1e36 / P)`.
* Upper bound for "collateral a liquidator would seize": `S = min(C, D * LIF * 1e36 / P)`.
* Bad debt: if the position's collateral reaches 0 with borrow shares left, the remaining debt is written off
  against suppliers (`badDebtAssets` in `Liquidate`). With all collateral seized, bad debt
  `= D - C * P / (1e36 * LIF)` when `C * P / 1e36 < D * LIF`.
* Underwater test: `C * P / 1e36 < D`.
* Pre-liquidation (when a borrower has authorized a PreLiquidation contract): a separate, softer path between
  `preLltv` and `LLTV` with linear close factor `preLCF1..preLCF2` and incentive `preLIF1..preLIF2`; none registered
  for these markets.

### 3.6 Feasibility

Readable at latest block from free RPC: **yes**, because markets, oracle prices and positions are `eth_call` views on
the singleton and the borrower set is enumerable from five indexed events (publicnode accepted 50,000-block
windows from block 51,002,618 on; blocks before about 51.0 M returned "Archive requests require a personal token",
and base.drpc.org rejected even 2,000-block windows at the time of this note, so the two oldest dust markets were
covered through the Morpho API only).

## 4. Others

| Protocol | Finding | Size | How positions would be read |
|---|---|---|---|
| Euler v2 (EVK, factory `0x7F321498A801A191a93C840750ed637149dDf8D0`, source https://raw.githubusercontent.com/euler-xyz/euler-interfaces/master/addresses/8453/CoreAddresses.json) | Factory `getProxyListLength()` = 457 vaults; 22 have a stock token as `asset()`: 20 escrow-style (`oracle() = 0`, no borrows) and two NVDAc vaults with a USD-unit oracle router and 0 assets. Scanning every vault's `LTVList()` found one USDC borrow vault `0x4c1aeda9b43efcf1da1d1755b18802aabe90f61e` (453,304 USDC borrowed against other collateral) that lists NVDAc escrow vault `0xfe885b1cfd237e8ed2d839335143752ee15856ba` (borrow LTV 0.90, liquidation LTV 0.92); that vault holds 0. | 0 USD of stock collateral backing debt; about 2,300 USD of stock tokens idle across the 22 vaults at the 24/5 feed prices (largest: GOOGLc 2.45 tokens, MSTRc 4.10, AAPLc 0.99, NVDAc 1.44, METAc 0.44, SPCXc 1.21) | EVC accounts: borrowers from the borrow vault's `Borrow` events, collateral via `balanceOf` on the collateral vault, health via the borrow vault's `accountLiquidity(account, true)`; liquidation via `LTVFull` and Euler's dynamic discount. |
| Fluid, Moonwell, Compound, Seamless, others | No pool with any of the 298 official token addresses as underlying on Base in DefiLlama's yields set (https://yields.llama.fi/pools, read 2026-11-08); only `aave-v4` and `morpho-blue` appear as lending protocols. No on-chain check. | none found | not applicable |
| Wrappers that hold stock tokens (not lending markets) | Pendle PT-GOOGLc / PT-NVDAc, Superform SuperVaults, IPOR Fusion "carry" vaults, Makina, Aerodrome / Uniswap pools appear in the same DefiLlama set. A wrapper accepted as collateral elsewhere would be a second-order exposure; the Morpho API search found only empty `vAAPLc` markets. IPOR / Superform vaults may themselves be borrowers on Aave V4 or Morpho and then appear in the position reads above. | not measured | not applicable |

## 5. Shock computation, as run on the snapshot

Illustrative only: same blocks as 3.4 and 2.5, feed answers frozen since Friday, shock applied to the stock feed
answer(s), USDC price unchanged (Morpho: 1 by construction; Aave V4: 0.99976765). USD at the shocked oracle price.
Script logic is the formulas of 2.6 and 3.5; nothing below is a forecast.

### 5.1 Morpho (each market is isolated; the shock is to that market's feed)

"Liquidatable" = positions with `C * P' * LLTV < D`. "Seizable" = `min(C * P', D * LIF)` summed over them (no close
factor, so a liquidator can take this in one call). Underwater = `C * P' < D`.

| Market | Borrowers | Shock | Liquidatable positions | Their collateral USD | Seizable USD | Their debt USDC | Underwater positions / debt |
|---|---|---|---|---|---|---|---|
| AAPLc 0.625 | 16 | 5 % / 10 % | 0 / 0 | 0 | 0 | 0 | 0 |
| | | 20 % | 3 | 17,685.76 | 13,083.63 | 11,611.72 | 0 |
| NVDAc 0.625 | 15 | 5 % | 0 | 0 | 0 | 0 | 0 |
| | | 10 % | 1 | 7.86 | 5.66 | 5.02 | 0 |
| | | 20 % | 2 | 22.06 | 17.01 | 15.09 | 0 |
| METAc 0.625 | 8 | 5 % | 0 | 0 | 0 | 0 | 0 |
| | | 10 % | 1 | 21.36 | 15.82 | 14.04 | 0 |
| | | 20 % | 3 | 34.31 | 27.10 | 24.05 | 0 |
| SPCXc 0.625 | 8 | 5 % / 10 % | 0 / 0 | 0 | 0 | 0 | 0 |
| | | 20 % | 1 | 6.69 | 4.86 | 4.31 | 0 |
| GOOGLc 0.77 | 11 | 5 % | 0 | 0 | 0 | 0 | 0 |
| | | 10 % | 1 | 11.34 | 9.55 | 8.89 | 0 |
| | | 20 % | 3 | 35.06 | 30.65 | 28.53 | 0 |
| AMZNc, MSFTc, TSLAc, GOOGLc 0.625, NVDAc 0.77 unlisted | 1 to 2 each | up to 20 % | 0 | 0 | 0 | 0 | 0 |

### 5.2 Aave V4 (one spoke, cross-collateral)

Convention: a single-token shock moves only that reserve's price; "ALL" moves all eight stock prices together.
"Liquidatable" = users with `HF' < 1`; their collateral is all enabled collateral (column 4) and the part held in the
shocked token(s) (column 5). "Seized" = one `liquidationCall` per liquidatable user against the largest shocked
collateral reserve, repaying up to the amount that restores HF 1.24 (2.6), with the dust rules applied; a second call
on another reserve is possible when the first exhausts a reserve, so this column is a lower bound for multi-collateral
users.

| Shock | Liquidatable users | Their collateral USD | of which in shocked token(s) | Seized, one call (USD) | Their debt USD | Underwater users |
|---|---|---|---|---|---|---|
| none | 1 | 2 | 2 | 0 | 1 | 0 |
| ALL 5 % | 6 | 5,158 | 5,158 | 1,702 | 3,777 | 0 |
| ALL 10 % | 19 | 12,261 | 12,261 | 5,739 | 9,466 | 0 |
| ALL 20 % | 50 | 1,213,219 | 1,213,219 | 653,684 | 949,614 | 0 |
| GOOGLc 5 / 10 / 20 % | 1 / 5 / 11 | 2 / 737 / 815,164 | 0 / 735 / 811,184 | 0 / 598 / 474,700 | 1 / 571 / 659,468 | 0 |
| METAc 5 / 10 / 20 % | 1 / 1 / 3 | 2 / 2 / 287,651 | 0 / 0 / 287,649 | 0 / 0 / 119,933 | 1 / 1 / 201,517 | 0 |
| MSFTc 5 / 10 / 20 % | 2 / 2 / 5 | 2 / 2 / 44,798 | 0 / 0 / 42,467 | 0 / 0 / 26,773 | 1 / 1 / 37,098 | 0 |
| NVDAc 5 / 10 / 20 % | 2 / 4 / 9 | 38 / 344 / 5,760 | 36 / 342 / 2,132 | 27 / 259 / 1,994 | 26 / 248 / 4,306 | 0 |
| AAPLc 5 / 10 / 20 % | 1 / 2 / 7 | 2 / 3 / 2,874 | 0 / 1 / 1,337 | 0 / 1 / 1,324 | 1 / 2 / 2,362 | 0 |
| AMZNc 5 / 10 / 20 % | 1 / 2 / 5 | 2 / 2 / 1,744 | 0 / 1 / 1,014 | 0 / 1 / 1,014 | 1 / 1 / 1,367 | 0 |
| SPCXc 5 / 10 / 20 % | 1 / 2 / 3 | 2 / 536 / 477 | 0 / 534 / 475 | 0 / 318 / 320 | 1 / 301 / 302 | 0 |
| TSLAc 5 / 10 / 20 % | 2 / 3 / 4 | 2 / 168 / 164 | 0 / 166 / 162 | 0 / 115 / 126 | 1 / 111 / 121 | 0 |

(The "none" row is the one position already below HF 1 at the frozen Friday prices: 1.81 USD of collateral spread
over seven reserves, so no single call takes more than about 0.47 USD and the column rounds to 0.) No position on
either protocol is underwater at any of the three shock sizes. Concentration: the GOOGLc 20 % row is mostly one
GOOGLc-only position (602,109 USD debt, HF 1.174 before the shock, 0.940 after, 744,352 USD collateral after the
shock), plus one of 50,180 USD debt; the METAc 20 % row is mostly one METAc-only position (200,525 USD debt, HF 0.928
after the shock). The larger GOOGLc-only position (921,864 USDC, HF 1.400) stays above 1 at 20 % (1.400 x 0.8 = 1.12).

## 6. Reproduction notes

* Endpoints used: `base.drpc.org` for `eth_call` and historical `eth_getCode` until it answered 429 ("Public endpoint
  rate limit"), then `mainnet.base.org` for the Multicall3 batches (100 to 150 calls per `eth_call`; the Aave V4 user
  read is about 120 batches); `base-rpc.publicnode.com` for `eth_getLogs` (50,000-block windows, about 13 s per call;
  no archive below about block 51.0 M). `mainnet.base.org` answered `eth_getLogs` with 429, and `base.drpc.org`
  rejected `eth_getLogs` over 100 blocks with the message "ranges over 10000 blocks are not supported on free plan"
  even for 1,000-block windows, so its limit differs from the 10,000 measured earlier in the day.
* A full refresh at about 1 request per second: Morpho logs 80 calls, Aave V4 logs 70 calls, position reads about
  130 `eth_call`s; under 25 minutes, dominated by publicnode latency.
* Selectors and topics were computed with keccak-256 over the canonical signatures given above; tuple arguments are
  written in their ABI form, e.g. `IHubBase.PremiumDelta` is `(int256,int256,uint256)` and `ReserveFlags` is `uint8`.
* Sources fetched: Morpho Blue `EventsLib.sol`, `ConstantsLib.sol`, `Morpho.sol`, `SharesMathLib.sol`, `IMorpho.sol`;
  Aave V4 `ISpoke.sol`, `Spoke.sol`, `LiquidationLogic.sol`, `AaveOracle.sol`, `SpokeUtils.sol`, `IHubBase.sol`;
  address book `AaveV4Base.sol`, `AaveV4.sol`, `.gitmodules`.
