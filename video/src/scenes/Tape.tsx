import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import data from "../data.json";
import { BAR, BEAT, C, Count, MONO, ramp, Slam, Stage, useExit } from "../kit";

// Bars 12-14: every token-weekend since Aug 24 as a dot, landing on sixteenth notes.
const LIM = 350;

export const Tape: React.FC = () => {
  const frame = useCurrentFrame();
  const out = useExit(3 * BAR, 6);
  const S = 760;
  const M = 30;
  const sx = (v: number) => M + ((Math.max(-LIM, Math.min(LIM, v)) + LIM) / (2 * LIM)) * (S - 2 * M);
  const sy = (v: number) => S - M - ((Math.max(-LIM, Math.min(LIM, v)) + LIM) / (2 * LIM)) * (S - 2 * M);
  const pts = [...data.points].sort((a, b) => Math.abs(a[0]) + Math.abs(a[1]) - (Math.abs(b[0]) + Math.abs(b[1])));
  const diag = ramp(frame, 4, 40);
  return (
    <Stage glowX={78} glowY={50} glow={0.2}>
      <AbsoluteFill style={{ padding: "120px 110px", flexDirection: "row", gap: 80, opacity: out }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 96, fontWeight: 700, letterSpacing: "-0.05em", lineHeight: 1 }}>
            <Slam at={0}>The weekend price</Slam>
            <br />
            <Slam at={6}>is a hint,</Slam>
            <br />
            <Slam at={BEAT} color={C.accent}>not an answer.</Slam>
          </div>
          <div style={{ marginTop: 50, display: "grid", gap: 0 }}>
            {[
              { at: BAR, n: data.median_error_bps, f: (v: number) => `${v.toFixed(0)} bps`, k: "median miss of the weekend DEX price at the reopen" },
              { at: BAR + BEAT * 2, n: (data.direction_hit_rate ?? 0) * 100, f: (v: number) => `${v.toFixed(0)}%`, k: "of weekends it had the direction right" },
              { at: 2 * BAR, n: data.weekends, f: (v: number) => `${Math.round(v)}`, k: "weekends and holidays measured since Aug 24" },
            ].map((r) => (
              <div
                key={r.k}
                style={{ display: "flex", alignItems: "baseline", gap: 30, padding: "22px 0", borderTop: `1px solid ${C.line}`, opacity: ramp(frame, r.at, r.at + 8) }}
              >
                <span style={{ font: `600 72px ${MONO}`, letterSpacing: "-0.04em", minWidth: 260 }}>
                  <Count a={r.at} b={r.at + 24} to={r.n} fmt={r.f} />
                </span>
                <span style={{ fontSize: 36, color: C.muted, lineHeight: 1.25 }}>{r.k}</span>
              </div>
            ))}
          </div>
        </div>
        <div style={{ width: S, height: S, background: C.surface, border: `1px solid ${C.line}`, borderRadius: 28, alignSelf: "center" }}>
          <svg width={S} height={S}>
            {[-LIM, -LIM / 2, 0, LIM / 2, LIM].map((v) => (
              <g key={v}>
                <line x1={M} x2={S - M} y1={sy(v)} y2={sy(v)} stroke={v === 0 ? "rgba(255,255,255,0.22)" : C.line} />
                <line y1={M} y2={S - M} x1={sx(v)} x2={sx(v)} stroke={v === 0 ? "rgba(255,255,255,0.22)" : C.line} />
              </g>
            ))}
            <line
              x1={sx(-LIM)}
              y1={sy(-LIM)}
              x2={sx(-LIM) + (sx(LIM) - sx(-LIM)) * diag}
              y2={sy(-LIM) + (sy(LIM) - sy(-LIM)) * diag}
              stroke={C.fg}
              strokeOpacity={0.5}
              strokeWidth={2}
              strokeDasharray="8 10"
            />
            {pts.map(([x, y], i) => {
              const at = 8 + i * 0.95;
              const k = ramp(frame, at, at + 8);
              return <circle key={i} cx={sx(x)} cy={sy(y)} r={9 * k} fill={C.accent} fillOpacity={0.78} />;
            })}
            <text x={S - M - 6} y={sy(0) - 14} textAnchor="end" fill={C.muted} style={{ font: `500 22px ${MONO}` }}>
              weekend gap
            </text>
            <text x={sx(0) + 14} y={M + 26} fill={C.muted} style={{ font: `500 22px ${MONO}` }}>
              reopen move
            </text>
          </svg>
        </div>
      </AbsoluteFill>
    </Stage>
  );
};
