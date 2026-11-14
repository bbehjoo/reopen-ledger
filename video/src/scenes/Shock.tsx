import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import data from "../data.json";
import { BAR, BEAT, C, Count, MONO, ramp, Slam, Stage, usd, useExit } from "../kit";

// Bars 9-11: the -20% shock from the absorb snapshot. Rows land on eighth notes.
export const Shock: React.FC = () => {
  const frame = useCurrentFrame();
  const sh = data.shock20;
  const max = Math.max(...sh.tokens.map((t) => Math.max(t.flow, t.depth)));
  const out = useExit(3 * BAR, 6);
  return (
    <Stage glowX={85} glowY={80} glow={0.2}>
      <AbsoluteFill style={{ padding: "110px 120px", opacity: out }}>
        <div style={{ fontSize: 104, fontWeight: 700, letterSpacing: "-0.05em", lineHeight: 1 }}>
          <Slam at={0}>If it reopens</Slam> <Slam at={6} color={C.accent}>20% lower:</Slam>
        </div>
        <div style={{ display: "flex", gap: 90, marginTop: 70 }}>
          <div style={{ flex: 1.35 }}>
            <div style={{ display: "flex", gap: 34, font: `500 26px ${MONO}`, color: C.muted, marginBottom: 18, opacity: ramp(frame, 10, 18) }}>
              <span>
                <i style={{ display: "inline-block", width: 26, height: 12, borderRadius: 6, background: "rgba(255,255,255,0.28)", marginRight: 12 }} />
                pool depth, 5% below
              </span>
              <span>
                <i style={{ display: "inline-block", width: 26, height: 12, borderRadius: 6, background: C.accent, marginRight: 12 }} />
                liquidation flow
              </span>
            </div>
            {sh.tokens.map((t, i) => {
              const at = BEAT + i * (BEAT / 2);
              const g = ramp(frame, at, at + 22);
              return (
                <div
                  key={t.s}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "190px 1fr 210px",
                    alignItems: "center",
                    gap: 24,
                    padding: "16px 0",
                    borderBottom: `1px solid ${C.line}`,
                    opacity: ramp(frame, at, at + 6),
                  }}
                >
                  <span style={{ fontSize: 38, fontWeight: 650 }}>{t.s}</span>
                  <div style={{ display: "grid", gap: 8 }}>
                    <div style={{ height: 14, borderRadius: 7, background: "rgba(255,255,255,0.28)", width: `${Math.max(0.4, (t.depth / max) * 100 * g)}%` }} />
                    <div style={{ height: 14, borderRadius: 7, background: C.accent, width: `${Math.max(0.4, (t.flow / max) * 100 * g)}%` }} />
                  </div>
                  <span style={{ font: `500 28px/1.3 ${MONO}`, textAlign: "right", color: C.muted }}>
                    {usd(t.depth * g)}
                    <br />
                    <b style={{ color: C.accentText }}>{usd(t.flow * g)}</b>
                  </span>
                </div>
              );
            })}
          </div>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 34, paddingTop: 20 }}>
            <div style={{ opacity: ramp(frame, 2 * BEAT, 2 * BEAT + 8) }}>
              <div style={{ fontSize: 150, fontWeight: 700, letterSpacing: "-0.055em", lineHeight: 1, color: C.accent }}>
                <Count a={2 * BEAT} b={BAR + BEAT} to={sh.flow} fmt={(v) => usd(v)} />
              </div>
              <div style={{ fontSize: 38, color: C.muted, marginTop: 10 }}>would be liquidated</div>
            </div>
            <div style={{ opacity: ramp(frame, 3 * BEAT, 3 * BEAT + 8) }}>
              <div style={{ fontSize: 150, fontWeight: 700, letterSpacing: "-0.055em", lineHeight: 1 }}>
                <Count a={3 * BEAT} b={BAR + 2 * BEAT} to={sh.depth} fmt={(v) => usd(v)} />
              </div>
              <div style={{ fontSize: 38, color: C.muted, marginTop: 10 }}>of pool depth to absorb it</div>
            </div>
            <div style={{ fontSize: 44, fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1.2, marginTop: 20, opacity: ramp(frame, 2 * BAR, 2 * BAR + 10) }}>
              {sh.over} of {sh.n} tokens: more flow than their pools hold.
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </Stage>
  );
};
