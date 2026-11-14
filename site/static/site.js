// Live parts of the site: entry reveals, the freeze clock, the "now" marker on the week, the shock toggle.
// Everything reads data embedded in the page by the site builder; nothing is fetched and nothing is sent.
"use strict";

(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const data = (id) => { const el = document.getElementById(id); return el ? JSON.parse(el.textContent) : null; };
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // entry reveals
  const io = "IntersectionObserver" in window && !reduce ? new IntersectionObserver((es) => {
    for (const e of es) if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
  }, { rootMargin: "0px 0px -12% 0px", threshold: 0.12 }) : null;
  for (const el of $$(".rv, .chart")) io ? io.observe(el) : el.classList.add("in");

  // freeze clock and week marker
  const spans = data("spans");
  const pad = (n) => String(n).padStart(2, "0");
  const hms = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}`; };
  function tick() {
    if (!spans) return;
    const now = Date.now();
    const cur = spans.spans.find((s) => s.start <= now && now < s.reopen);
    const next = spans.spans.find((s) => s.start > now);
    const pill = $("#state"), clock = $("#clock"), k = $("#clock-k");
    if (pill && clock && k) {
      if (cur) {
        pill.className = "state frozen"; pill.lastChild.textContent = "Reference frozen";
        clock.textContent = hms(cur.reopen - now);
        k.textContent = `until the reopen, ${cur.reopen_et}. Frozen for ${hms(now - cur.start)}.`;
      } else if (next) {
        pill.className = "state live"; pill.lastChild.textContent = "Reference live";
        clock.textContent = hms(next.start - now);
        k.textContent = `until the next freeze, ${next.start_et}.`;
      }
    }
    const bar = $(".week .bar"), mark = $(".week .now");
    if (bar && mark) {
      const a = Number(bar.dataset.from), b = Number(bar.dataset.to);
      if (now >= a && now < b) {
        const x = (now - a) / (b - a);
        mark.style.left = `${(x * 100).toFixed(3)}%`; mark.hidden = false; mark.classList.toggle("flip", x > 0.9);
      } else mark.hidden = true;
    }
  }
  tick(); setInterval(tick, 1000);

  // hero prediction card: one tap per stock (Lower 35%, Higher 65%, tap again to clear); picks go to the form
  const go = document.getElementById("hp-go");
  if (go) {
    const rows = $$(".pick[data-sym]");
    const sync = () => {
      const picks = rows.map((r) => { const b = $("button[aria-pressed=true]", r); return b ? `${r.dataset.sym}:${b.dataset.v}` : ""; }).filter(Boolean);
      go.href = "commit.html" + (picks.length ? "?p=" + picks.join(",") : "");
    };
    for (const r of rows) for (const b of $$("button", r)) b.addEventListener("click", () => {
      const on = b.getAttribute("aria-pressed") === "true";
      for (const x of $$("button", r)) x.setAttribute("aria-pressed", "false");
      b.setAttribute("aria-pressed", String(!on));
      sync();
    });
    sync();
    // With a wallet and at least one tap, "Commit on Base" sends the prediction from here (commit.js send());
    // without either, the link opens the full form, which explains the rest.
    const st = document.getElementById("hp-status");
    go.addEventListener("click", async (ev) => {
      const picks = rows.map((r) => ({ r, b: $("button[aria-pressed=true]", r) })).filter((x) => x.b);
      const eth = window.ethereum;
      if (!picks.length || !eth || typeof send !== "function") return;
      ev.preventDefault();
      try {
        st.textContent = "Reading the open window...";
        const open = await (await fetch("data/form.json", { cache: "no-store" })).json();
        const now = Date.now();
        const win = open.windows.filter((w) => w.cutoff_ms - now > 120000).sort((a, b) => a.cutoff_ms - b.cutoff_ms)[0];
        if (!open.ledger || !win) { location.href = go.href; return; }
        const onSlate = new Set(open.slate.map((t) => t.address.toLowerCase()));
        const calls = picks.map(({ r, b }) => ({ token: r.dataset.token, p: Number(b.dataset.v) / 100 })).filter((c) => onSlate.has(c.token));
        if (!calls.length) { location.href = go.href; return; }
        const [from] = await eth.request({ method: "eth_requestAccounts" });
        const chainHex = "0x" + open.ledger.chain_id.toString(16);
        if ((await eth.request({ method: "eth_chainId" })) !== chainHex) {
          await eth.request({ method: "wallet_switchEthereumChain", params: [{ chainId: chainHex }] });
        }
        st.textContent = "Confirm in your wallet...";
        const hash = await send(eth, from, chainHex, open.ledger.address, win.id, encodeCalls(calls), open.builder_codes || [], st);
        st.innerHTML = `On the record for ${win.label}: <a href="https://basescan.org/tx/${hash}">view the transaction</a>. ` +
          "It stays sealed until the window resolves, then shows on the board.";
      } catch (e) {
        st.textContent = `Not sent: ${e && e.message ? e.message : e}`;
      }
    });
  }

  // shock toggle
  const ab = data("absorb-data");
  const usd = (v) => v >= 1e6 ? `$${(v / 1e6).toFixed(2)}M` : v >= 1e3 ? `$${(v / 1e3).toFixed(1)}k` : `$${Math.round(v)}`;
  function shock(s) {
    if (!ab) return;
    for (const b of $$(".seg button")) b.setAttribute("aria-pressed", String(b.dataset.s === s));
    let depth = 0, flow = 0, over = 0, max = 1;
    for (const t of ab.tokens) { depth += t.depth[s]; flow += t.flow[s]; if (t.flow[s] > t.depth[s]) over++; max = Math.max(max, t.depth[s], t.flow[s]); }
    $("#ab-flow").textContent = usd(flow); $("#ab-depth").textContent = usd(depth);
    $("#ab-note").textContent = over
      ? `At ${s}% lower, ${over} of ${ab.tokens.length} tokens would see more liquidation flow than their pools hold in the 5% below.`
      : `At ${s}% lower, every token's pools hold more than its liquidation flow in the 5% below.`;
    for (const row of $$(".flows .row")) {
      const t = ab.tokens[Number(row.dataset.i)];
      $(".b.depth", row).style.transform = `scaleX(${Math.max(t.depth[s] / max, 0.004)})`;
      $(".b.flow", row).style.transform = `scaleX(${t.flow[s] ? Math.max(t.flow[s] / max, 0.01) : 0})`;
      $(".v", row).innerHTML = `${usd(t.depth[s])}<br><b>${t.flow[s] ? usd(t.flow[s]) : "$0"}</b>`;
    }
  }
  for (const b of $$(".seg button")) b.addEventListener("click", () => shock(b.dataset.s));
  if (ab) shock(ab.initial);

  // live freeze view (live.html): prices read now, positions and depth from the dated snapshot
  const lv = data("live-data");
  if (lv) {
    const RPC = "https://mainnet.base.org";
    const lerp = (pts, x) => {
      if (x <= pts[0][0]) return pts[0][1];
      for (let i = 1; i < pts.length; i++) if (x <= pts[i][0]) {
        const [x0, y0] = pts[i - 1], [x1, y1] = pts[i];
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0);
      }
      return pts[pts.length - 1][1];
    };
    const flowAt = (t, s) => lerp([[0, 0], [5, t.flow["5"]], [10, t.flow["10"]], [20, t.flow["20"]]], s);
    const depthAt = (t, s) => lerp([[5, t.depth["5"]], [10, t.depth["10"]], [20, t.depth["20"]]], s);
    const money = (v) => v >= 1e6 ? `$${(v / 1e6).toFixed(2)}M` : v >= 1e3 ? `$${(v / 1e3).toFixed(1)}k` : `$${Math.round(v)}`;
    async function refs() {
      const ts = lv.tokens.filter((t) => t.proxy);
      const body = ts.map((t, i) => ({ jsonrpc: "2.0", id: i, method: "eth_call", params: [{ to: t.proxy, data: "0xfeaf968c" }, "latest"] }));
      const out = {};
      try {
        const res = await (await fetch(RPC, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();
        for (const r of res) {
          if (!r.result || r.result.length < 130) continue;
          let a = BigInt("0x" + r.result.slice(66, 130));
          if (a >= (1n << 255n)) a -= (1n << 256n);
          const t = ts[r.id];
          if (a > 0n) out[t.a] = Number(a) / 10 ** t.dec;
        }
      } catch (e) { /* fall back to the snapshot's reference values */ }
      for (const t of lv.tokens) if (!out[t.a] && t.ref) out[t.a] = t.ref;
      return out;
    }
    async function dex() {
      const out = {};
      try {
        const pairs = await (await fetch("https://api.dexscreener.com/tokens/v1/base/" + lv.tokens.map((t) => t.a).join(","))).json();
        const best = {};
        for (const p of Array.isArray(pairs) ? pairs : []) {
          const a = ((p.baseToken || {}).address || "").toLowerCase(), liq = Number((p.liquidity || {}).usd || 0);
          if (a && p.priceUsd && liq > (best[a] || -1)) { best[a] = liq; out[a] = Number(p.priceUsd); }
        }
      } catch (e) { /* leave the DEX column empty */ }
      return out;
    }
    async function update() {
      const [ref, px] = await Promise.all([refs(), dex()]);
      let flow = 0, depth = 0, over = 0, priced = 0;
      for (const t of lv.tokens) {
        const row = $(`tr[data-a="${t.a}"]`);
        const r = ref[t.a], p = px[t.a];
        $(".ref", row).textContent = r ? `$${r.toFixed(2)}` : "–";
        $(".dex", row).textContent = p ? `$${p.toFixed(2)}` : "–";
        if (!r || !p || Math.abs(p / r - 1) > 0.3) {
          for (const k of [".gap", ".flow", ".depth"]) $(k, row).textContent = "–";
          $(".flag", row).textContent = p && r ? "pool far from reference" : "no DEX price";
          continue;
        }
        priced++;
        const gap = (p / r - 1) * 100, s = Math.max(0, -gap);
        const f = s > 0 ? flowAt(t, s) : 0, d = depthAt(t, Math.max(s, 5));
        flow += f; depth += d;
        $(".gap", row).textContent = `${gap >= 0 ? "+" : ""}${gap.toFixed(2)}%`;
        $(".gap", row).className = "num gap " + (gap < 0 ? "neg" : "pos");
        $(".flow", row).textContent = money(f);
        $(".depth", row).textContent = money(d);
        const hot = f > d && f > 0;
        if (hot) over++;
        $(".flag", row).textContent = hot ? "flow above depth" : "";
        row.classList.toggle("hot", hot);
      }
      $("#lv-flow").textContent = money(flow);
      $("#lv-depth").textContent = money(depth);
      $("#lv-note").textContent = `${priced} of ${lv.tokens.length} stocks priced. ` + (over
        ? `${over} would see more liquidation flow than their pools hold. `
        : "Every priced stock's pools hold its liquidation flow at today's DEX price. ") +
        `Updated ${new Date().toLocaleTimeString()}.`;
    }
    update();
    setInterval(update, 60000);
  }
})();
