# Depth engine against an on-chain quoter

Run 2026-11-08 at Base block 54,971,338 with `scripts/depth_check.py`, read-only.

For each pool: read the pool state (slot0, liquidity, tick bitmap, initialized ticks) at the block, compute
with `callrec.depth` the USDC paid out as the token price moves down 0.2%, 1% and 3%, and the token amount
that move takes (gross of the pool fee). Then ask Uniswap's QuoterV2 on Base
(`0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a`, `quoteExactInputSingle`) for the USDC out for that token
amount at the same block.

| token | pool | move | ours (USDC) | QuoterV2 (USDC) | difference |
|---|---|---:|---:|---:|---:|
| GOOGLc | Uniswap v3 `0x1f52f46b...` (1%) | 0.2% | 267.23 | 267.23 | 0.000 bps |
| GOOGLc | Uniswap v3 `0x1f52f46b...` (1%) | 1.0% | 827.04 | 827.04 | 0.000 bps |
| GOOGLc | Uniswap v3 `0x1f52f46b...` (1%) | 3.0% | 1,947.49 | 1,947.49 | 0.000 bps |
| GOOGLc | Uniswap v3 `0x8634ee41...` (0.3%) | 0.2% | 15.34 | 15.34 | 0.002 bps |
| GOOGLc | Uniswap v3 `0x8634ee41...` (0.3%) | 1.0% | 186.27 | 186.27 | 0.000 bps |
| GOOGLc | Uniswap v3 `0x8634ee41...` (0.3%) | 3.0% | 341.11 | 341.11 | 0.000 bps |

Reading:
- The tick walk, the liquidityNet crossings and the decimal handling agree with the quoter to rounding.
- Aerodrome Slipstream and Aero CL pools use the same concentrated-liquidity math and the same `ticks()` layout.
  The Slipstream QuoterV2 address tried (`0x254cF9E1...`) did not answer for these pools, so those pools
  were not quoter-checked.
- Uniswap v4 pools go through StateView with the same math.
- One Uniswap v3 NVDAc pool (`0x9778aad8...`) had zero in-range liquidity and no initialized ticks at the
  block, although an API listed $46.6k of reserves for it. Depth is read from pool state, never from API
  reserves.
