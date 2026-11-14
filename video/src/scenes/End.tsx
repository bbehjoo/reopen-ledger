import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { BAR, C, Mark, MONO, ramp, Stage, useSpring } from "../kit";

// Bars 23-24: the final impact. Mark, name, link; hold, then fade with the tail.
export const End: React.FC = () => {
  const frame = useCurrentFrame();
  const s = useSpring(0, 11, 0.7);
  const flash = interpolate(frame, [0, 5], [0.85, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const fade = ramp(frame, 2 * BAR - 24, 2 * BAR, 1, 0);
  return (
    <Stage glowX={50} glowY={42} glow={0.34}>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", opacity: fade }}>
        <div style={{ display: "flex", alignItems: "center", gap: 36, scale: String(0.8 + 0.2 * s) }}>
          <div style={{ rotate: `${(1 - s) * -30}deg` }}>
            <Mark size={150} />
          </div>
          <span style={{ fontSize: 150, fontWeight: 700, letterSpacing: "-0.055em" }}>Reopen Ledger</span>
        </div>
        <div style={{ marginTop: 50, font: `500 48px ${MONO}`, color: C.fg, opacity: ramp(frame, 10, 20) }}>
          bbehjoo.github.io/reopen-ledger
        </div>
        <div style={{ marginTop: 22, fontSize: 38, color: C.muted, opacity: ramp(frame, 18, 28) }}>
          Live on Base. Open code, open data. Call the reopen.
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ backgroundColor: "#fff", opacity: flash }} />
    </Stage>
  );
};
