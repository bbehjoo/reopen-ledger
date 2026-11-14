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

async function main() {
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
  if (!open.ledger) { status.textContent = "The contract is not deployed yet; records open at launch."; return; }
  for (const t of open.slate) {
    const row = document.createElement("div");
    row.className = "token-row";
    row.innerHTML = `<label for="p-${t.address}"><span class="sym">${t.symbol}</span>` +
      `<span class="name">${t.name ?? ""}</span></label>` +
      `<input type="range" min="0" max="100" step="1" value="50" id="p-${t.address}" data-token="${t.address}">` +
      `<output for="p-${t.address}">50%</output>`;
    list.appendChild(row);
    const input = row.querySelector("input");
    const out = row.querySelector("output");
    input.addEventListener("input", () => { out.textContent = `${input.value}%`; });
  }
  document.getElementById("ledger").textContent = open.ledger.address;
  document.getElementById("commit").addEventListener("click", async () => {
    const eth = window.ethereum;
    if (!eth) { status.textContent = "No browser wallet found."; return; }
    try {
      const [from] = await eth.request({ method: "eth_requestAccounts" });
      const chainHex = "0x" + open.ledger.chain_id.toString(16);
      if ((await eth.request({ method: "eth_chainId" })) !== chainHex) {
        await eth.request({ method: "wallet_switchEthereumChain", params: [{ chainId: chainHex }] });
      }
      const calls = [...list.querySelectorAll("input[type=range]")].map((i) => ({ token: i.dataset.token, p: Number(i.value) / 100 }));
      const data = calldata(Number(sel.value), encodeCalls(calls), open.builder_codes || []);
      status.textContent = "Waiting for the wallet...";
      const hash = await eth.request({ method: "eth_sendTransaction", params: [{ from, to: open.ledger.address, data, value: "0x0" }] });
      status.innerHTML = `On the record: transaction <code>${hash}</code>. The first record per wallet and window is the one that is scored; your probabilities appear on the board after the window resolves.`;
    } catch (e) {
      status.textContent = `Not sent: ${e && e.message ? e.message : e}`;
    }
  });
}

if (typeof document !== "undefined") main();
if (typeof module !== "undefined") module.exports = { encodeCalls, suffix, calldata };
