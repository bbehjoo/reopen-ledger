"""Depth engine against on-chain quoters at one block (docs/research/DEPTH-CHECK.md)."""
import sys
from callrec import pools, depthread
from callrec.depth import quote_out, _token_in
from callrec.rpcpool import RpcPool
from callrec.abi import selector, enc_uint, enc_address, words

r = RpcPool(["https://mainnet.base.org", "https://base.drpc.org"])
cfg = {e.get("address", "").lower(): e for e in pools.raw_config()["pools"]}
QUOTERS = {
    "uniswap-v3": ("0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a", "quoteExactInputSingle((address,address,uint256,uint24,uint160))", "fee"),
    "slipstream": ("0x254cF9E1E6e233aa1AC962CB9B05b2cfeAaE15b0", "quoteExactInputSingle((address,address,uint256,int24,uint160))", "spacing"),
}
block = r.block_number() - 20
out = []
for p in pools.load_pools():
    e = cfg.get(p.address)
    if not e or p.kind != "cl":
        continue
    kind = "uniswap-v3" if e["protocol"] == "uniswap-v3" else ("slipstream" if "gauges v3" in (e.get("protocol_detail") or "") else None)
    if kind is None:
        continue
    st, _ = depthread.read_cl(r, p, block)
    if st.liquidity == 0:
        continue
    q_addr, sig, mode = QUOTERS[kind]
    fee = float(e.get("fee") or p.fee or 0)
    p0 = st.token_price()
    for move in (0.002, 0.01, 0.03):
        p1 = p0 * (1 - move)
        usdc = quote_out(st, p0, p1)
        tin = _token_in(st, p0, p1) / (1 - fee)
        amt = int(tin * 10 ** p.dec_token)
        if amt == 0:
            continue
        arg = enc_uint(int(round(fee * 1e6))) if mode == "fee" else enc_uint(st.tick_spacing)
        data = selector(sig) + enc_address(p.token) + enc_address(p.quote) + enc_uint(amt) + arg + enc_uint(0)
        try:
            q = words(r.eth_call(q_addr, data, block))[0] / 10 ** p.dec_quote
        except Exception as ex:
            q = None
        diff = (usdc - q) / q * 1e4 if q else None
        out.append((e["stock_symbol"], kind, p.address, move, usdc, q, diff))
        print(e["stock_symbol"], kind, p.address[:10], f"move {move*100:.1f}%", f"ours {usdc:,.2f}", f"quoter {q if q is None else round(q, 2)}", f"diff_bps {None if diff is None else round(diff, 3)}", flush=True)
    if len({x[2] for x in out}) >= 4:
        break
print("block", block)
