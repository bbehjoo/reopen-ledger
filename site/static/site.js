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
})();
