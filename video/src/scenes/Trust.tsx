import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { BAR, C, MONO, ramp, Slam, Stage } from "../kit";

// Bars 21-22: one word per stab (beats 1 and 3 of each bar), then the house rule.
const WORDS: { at: number; w: string; k: string }[] = [
  { at: 0, w: "Signed.", k: "every daily export, Ed25519" },
  { at: 30, w: "Anchored.", k: "its hash on Base, once a day" },
  { at: 60, w: "Replayable.", k: "every number rebuilds from chain logs" },
];

export const Trust: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <Stage glowX={50} glowY={50} glow={0.16 + 0.1 * Math.max(0, 1 - ((frame % 30) / 12))}>
      <AbsoluteFill style={{ justifyContent: "center", padding: "0 150px" }}>
        {WORDS.map((r) => (
          <div key={r.w} style={{ display: "flex", alignItems: "baseline", gap: 40, opacity: frame < r.at ? 0 : ramp(frame, 90, 100, 1, 0.28) }}>
            <span style={{ fontSize: 150, fontWeight: 700, letterSpacing: "-0.055em", lineHeight: 1.08, minWidth: 900 }}>
              <Slam at={r.at}>{r.w}</Slam>
            </span>
            <span style={{ font: `500 34px ${MONO}`, color: C.muted, opacity: ramp(frame, r.at + 6, r.at + 14) }}>{r.k}</span>
          </div>
        ))}
        <div style={{ marginTop: 40, fontSize: 64, fontWeight: 650, letterSpacing: "-0.03em", color: C.accent, opacity: ramp(frame, 90, 98) }}>
          Measurements, not verdicts.
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ opacity: ramp(frame, 2 * BAR - 6, 2 * BAR, 0, 1), backgroundColor: C.bg }} />
    </Stage>
  );
};
