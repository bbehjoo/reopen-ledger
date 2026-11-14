import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { BAR, BEAT, C, MONO, ramp, Slam, Stage } from "../kit";

// Bars 0-3. Ticks under bar 0-1, the drop on bar 2 lands on "doesn't."
const DROP = 2 * BAR;

/** A schematic, not data: a moving line (the pools) and a line that stops (the reference). */
const Lines: React.FC<{ start: number }> = ({ start }) => {
  const frame = useCurrentFrame();
  const W = 1700;
  const H = 300;
  const freezeAt = 0.38;
  const prog = ramp(frame, start, start + 2 * BAR - 10, 0, 1);
  const n = 160;
  const pts: string[] = [];
  const ref: string[] = [];
  let y = 0;
  let frozenY = 0;
  for (let i = 0; i <= n * prog; i++) {
    const x = (i / n) * W;
    y = Math.sin(i / 6) * 34 + Math.sin(i / 2.3) * 12 + Math.sin(i / 17) * 46 + (i > n * 0.6 ? (i - n * 0.6) * 1.3 : 0);
    pts.push(`${x.toFixed(1)},${(H / 2 - y).toFixed(1)}`);
    if (i / n <= freezeAt) frozenY = y;
    ref.push(`${x.toFixed(1)},${(H / 2 - (i / n <= freezeAt ? y : frozenY)).toFixed(1)}`);
  }
  const fx = freezeAt * W;
  const showFreeze = prog > freezeAt;
  return (
    <svg width={W} height={H + 60} viewBox={`0 0 ${W} ${H + 60}`} style={{ overflow: "visible" }}>
      {showFreeze && (
        <rect x={fx} y={0} width={Math.max(0, prog * W - fx)} height={H} fill="rgba(255,106,43,0.07)" />
      )}
      {showFreeze && <line x1={fx} y1={-10} x2={fx} y2={H + 10} stroke={C.accent} strokeWidth={2} strokeDasharray="6 8" />}
      <polyline points={pts.join(" ")} fill="none" stroke={C.fg} strokeOpacity={0.55} strokeWidth={3} strokeLinejoin="round" />
      <polyline points={ref.join(" ")} fill="none" stroke={C.accent} strokeWidth={6} strokeLinejoin="round" strokeLinecap="round" />
      {showFreeze && (
        <text x={fx + 18} y={H + 46} fill={C.accentText} style={{ font: `600 30px ${MONO}`, letterSpacing: 2 }}>
          FRI 20:00 ET: REFERENCE FROZEN
        </text>
      )}
      <text x={0} y={H + 46} fill={C.muted} style={{ font: `500 28px ${MONO}` }}>
        tokens on Base, still moving
      </text>
    </svg>
  );
};

export const Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const before = frame < DROP;
  const flash = frame < DROP ? 0 : interpolate(frame, [DROP, DROP + 6], [0.9, 0], { extrapolateRight: "clamp" });
  const shake = frame >= DROP && frame < DROP + 10 ? Math.sin(frame * 9) * (DROP + 10 - frame) * 1.6 : 0;
  return (
    <Stage glowX={before ? 50 : 80} glowY={before ? 50 : 15} glow={before ? 0.1 + 0.06 * Math.sin(frame / 4) : 0.24}>
      {before ? (
        <AbsoluteFill style={{ justifyContent: "center", padding: "0 150px" }}>
          <div style={{ fontSize: 176, fontWeight: 700, letterSpacing: "-0.055em", lineHeight: 0.95 }}>
            <Slam at={0}>Stocks</Slam> <Slam at={BEAT}>trade</Slam>
            <br />
            <Slam at={2 * BEAT}>all</Slam> <Slam at={3 * BEAT}>weekend.</Slam>
          </div>
          <div
            style={{
              marginTop: 48,
              font: `500 34px ${MONO}`,
              color: C.muted,
              opacity: ramp(frame, BAR, BAR + 10),
              letterSpacing: 1,
            }}
          >
            Coinbase tokenized stocks, 24/7 on Base.
          </div>
        </AbsoluteFill>
      ) : (
        <AbsoluteFill style={{ padding: "120px 110px", translate: `${shake}px 0` }}>
          <div style={{ fontSize: 168, fontWeight: 700, letterSpacing: "-0.055em", lineHeight: 0.95 }}>
            <Slam at={DROP - 2}>Their price</Slam>{" "}
            <Slam at={DROP} color={C.accent}>
              doesn&apos;t.
            </Slam>
          </div>
          <div style={{ marginTop: 90 }}>
            <Lines start={DROP + 6} />
          </div>
        </AbsoluteFill>
      )}
      <AbsoluteFill style={{ backgroundColor: "#fff", opacity: flash }} />
    </Stage>
  );
};
