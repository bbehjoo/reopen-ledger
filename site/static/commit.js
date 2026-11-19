// Put a forecast on the record: one commit(windowId, 1, data) transaction to the CallLedger contract.
// No library: the calldata is built here (schema 1, METHODS.md section 4) and sent through the wallet's
// EIP-1193 provider. The contract holds no funds; the transaction carries no value.
"use strict";

const SELECTOR = "eda6e22e"; // commit(uint32,uint16,bytes)
const MARKER = "80218021802180218021802180218021";
const RET_NONE = "80000000";

function word(n) { return BigInt(n).toString(16).padStart(64, "0"); }
function hexByte(n) { return n.toString(16).padStart(2, "0"); }

function encodeCalls(calls) {
  const sorted = [...calls].sort((a, b) => (a.token < b.token ? -1 : 1));
  let h = "";
  for (const c of sorted) {
    const bps = Math.round(c.p * 10000);
    if (bps < 0 || bps > 10000) throw new Error("probability out of range");
    h += c.token.toLowerCase().slice(2) + bps.toString(16).padStart(4, "0") + RET_NONE;
  }
  return h;
}

function suffix(codes) {
  const raw = codes.join(",");
  let h = "";
  for (const ch of raw) h += hexByte(ch.charCodeAt(0));
  return h + hexByte(raw.length) + "00" + MARKER;
}

function calldata(windowId, dataHex, codes) {
  const n = dataHex.length / 2;
  const padded = dataHex + "0".repeat((64 - (dataHex.length % 64)) % 64);
  return "0x" + SELECTOR + word(windowId) + word(1) + word(96) + word(n) + padded + (codes.length ? suffix(codes) : "");
}

function fmt(ms) {
  return new Date(ms).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
}

// Smart wallets wrap the call, so a suffix appended to the calldata would not sit at the end of what Base reads.
// When the wallet supports the EIP-5792 dataSuffix capability, the Builder Code goes there (Base's Builder Code
// docs, "for app developers"); otherwise it is appended to the calldata, which is right for ordinary wallets.
// Gas: when the site has a paymaster (form.json paymaster_url, set from a secret at build time) and the wallet
// supports both paymasterService and dataSuffix, the call is sponsored and keeps its Builder Code. A wallet that
// cannot keep the code is never sponsored: attribution is not traded for free gas.
// A passkey wallet (below) is a Coinbase smart wallet: it takes both capabilities, so they are sent without asking.
async function send(eth, from, chainHex, to, windowId, dataHex, codes, status, paymasterUrl, passkey) {
  let caps = null;
  if (!passkey) {
    try {
      caps = await eth.request({ method: "wallet_getCapabilities", params: [from, [chainHex]] });
    } catch (e) { caps = null; }
  }
  const c = caps && (caps[chainHex] || caps[String(parseInt(chainHex, 16))]);
  const suffixOk = !!(passkey || (c && c.dataSuffix && c.dataSuffix.supported));
  const sponsor = !!(paymasterUrl && suffixOk && (passkey || (c.paymasterService && c.paymasterService.supported)));
  if (codes.length && suffixOk) {
    const capabilities = { dataSuffix: { value: "0x" + suffix(codes), optional: true } };
    if (sponsor) capabilities.paymasterService = { url: paymasterUrl };
    const res = await eth.request({ method: "wallet_sendCalls", params: [{
      version: "2.0.0", chainId: chainHex, from, atomicRequired: false,
      calls: [{ to, data: calldata(windowId, dataHex, []), value: "0x0" }],
      capabilities,
    }] });
    const id = typeof res === "string" ? res : res.id;
    status.textContent = (sponsor ? "Gas covered. " : "") + "Sent; waiting for it to be mined...";
    for (let i = 0; i < 60; i++) {
      const st = await eth.request({ method: "wallet_getCallsStatus", params: [id] });
      const r = st && st.receipts && st.receipts[0];
      if (r && r.transactionHash) return r.transactionHash;
      await new Promise((ok) => setTimeout(ok, 2000));
    }
    return id;
  }
  return eth.request({ method: "eth_sendTransaction", params: [{ from, to, data: calldata(windowId, dataHex, codes), value: "0x0" }] });
}

// Passkey sign-in for visitors without a browser wallet: Coinbase's Base Account SDK (2.6.0, Apache-2.0, vendored
// unchanged as base-account.min.js), loaded on first use. A Coinbase window creates or opens a smart wallet with a
// passkey (Face ID, fingerprint or a security key): no app, no seed phrase. Offered only when the site has a
// paymaster, because a new wallet holds no ETH; the Builder Code goes on every call as with any smart wallet.
const HERE = (typeof document !== "undefined" && document.currentScript && document.currentScript.src || "").replace(/commit\.js.*$/, "");
let passkeyP = null;
function passkeyWallet(open) {
  if (!passkeyP) {
    passkeyP = new Promise((ok, no) => {
      const make = () => {
        try {
          const chain = open.ledger.chain_id;
          const codes = open.builder_codes || [];
          const preference = { telemetry: false };
          if (codes.length) preference.attribution = { dataSuffix: "0x" + suffix(codes) };
          const sdk = window.createBaseAccountSDK({ appName: "Reopen Ledger", appLogoUrl: null, appChainIds: [chain],
            preference, paymasterUrls: { [chain]: open.paymaster_url } });
          ok(sdk.getProvider());
        } catch (e) { no(e); }
      };
      if (window.createBaseAccountSDK) { make(); return; }
      const s = document.createElement("script");
      s.src = HERE + "base-account.min.js";
      s.onload = make;
      s.onerror = () => { passkeyP = null; no(new Error("could not load the passkey sign-in")); };
      document.head.appendChild(s);
    });
  }
  return passkeyP;
}

async function main() {
  if (!document.getElementById("commit")) return; // loaded on the landing page for send(); the form lives on commit.html
  const status = document.getElementById("status");
  let open;
  try {
    open = await (await fetch("data/form.json", { cache: "no-store" })).json();
  } catch (e) {
    status.textContent = "Could not load the open windows (data/form.json).";
    return;
  }
  const sel = document.getElementById("window");
  const now = Date.now();
  const windows = open.windows.filter((w) => w.cutoff_ms > now);
  if (!windows.length) { status.textContent = "No window is open for records right now."; return; }
  for (const w of windows) {
    const o = document.createElement("option");
    o.value = String(w.id);
    o.textContent = `${w.label}: records count until ${fmt(w.cutoff_ms)}`;
    sel.appendChild(o);
  }
  const list = document.getElementById("tokens");
  // picks carried over from the landing page, e.g. ?p=NVDAc:62,TSLAc:41
  const preset = new Map();
  for (const kv of (new URLSearchParams(location.search).get("p") || "").split(",")) {
    const [sym, val] = kv.split(":");
    const n = Number(val);
    if (sym && Number.isInteger(n) && n >= 0 && n <= 100) preset.set(sym, n);
  }
  if (!open.ledger) { status.textContent = "The contract is not deployed yet; records open at launch."; return; }
  for (const t of open.slate) {
    const row = document.createElement("div");
    row.className = "token-row";
    row.innerHTML = `<label for="p-${t.address}"><span class="sym">${t.symbol}</span>` +
      `<span class="name">${t.name ?? ""}</span></label>` +
      `<input type="range" min="0" max="100" step="1" value="50" id="p-${t.address}" data-token="${t.address}">` +
      `<output for="p-${t.address}">50%</output>` +
      `<div class="tap" role="group" aria-label="${t.symbol} reopens"><button type="button" data-v="35">Lower</button>` +
      `<button type="button" data-v="50">Not sure</button><button type="button" data-v="65">Higher</button></div>`;
    list.appendChild(row);
    const input = row.querySelector("input");
    const out = row.querySelector("output");
    const taps = [...row.querySelectorAll(".tap button")];
    const mark = () => { for (const b of taps) b.setAttribute("aria-pressed", String(b.dataset.v === input.value)); };
    input.addEventListener("input", () => { out.textContent = `${input.value}%`; mark(); });
    for (const b of taps) b.addEventListener("click", () => { input.value = b.dataset.v; out.textContent = `${b.dataset.v}%`; mark(); });
    const v = preset.get(t.symbol);
    if (v !== undefined) { input.value = String(v); out.textContent = `${v}%`; }
    mark();
  }
  document.getElementById("ledger").textContent = open.ledger.address;
  const injected = window.ethereum;
  let pk = null;
  if (!injected && open.paymaster_url) passkeyWallet(open).then((p) => { pk = p; }).catch(() => {});
  document.getElementById("commit").addEventListener("click", async () => {
    if (!injected && !open.paymaster_url) { status.textContent = "No browser wallet found."; return; }
    try {
      const eth = injected || pk || await passkeyWallet(open);
      if (!injected) status.textContent = "Sign in with your passkey (Face ID or fingerprint)...";
      const [from] = await eth.request({ method: "eth_requestAccounts" });
      const chainHex = "0x" + open.ledger.chain_id.toString(16);
      if (injected && (await eth.request({ method: "eth_chainId" })) !== chainHex) {
        await eth.request({ method: "wallet_switchEthereumChain", params: [{ chainId: chainHex }] });
      }
      const calls = [...list.querySelectorAll("input[type=range]")].map((i) => ({ token: i.dataset.token, p: Number(i.value) / 100 }));
      const codes = open.builder_codes || [];
      status.textContent = "Waiting for the wallet...";
      const hash = await send(eth, from, chainHex, open.ledger.address, Number(sel.value), encodeCalls(calls), codes, status, open.paymaster_url, !injected);
      status.innerHTML = `On the record: transaction <a href="https://basescan.org/tx/${hash}"><code>${hash}</code></a>. The first record per wallet and window is the one that is scored; your probabilities appear on the board after the window resolves.`;
    } catch (e) {
      status.textContent = `Not sent: ${e && e.message ? e.message : e}`;
    }
  });
}

if (typeof document !== "undefined") main();
if (typeof module !== "undefined") module.exports = { encodeCalls, suffix, calldata, send };
