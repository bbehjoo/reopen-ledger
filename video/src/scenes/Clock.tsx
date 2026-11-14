import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import { BAR, BEAT, C, MONO, ramp, Stage, useExit, useSpring } from "../kit";

// Bars 4-5: 48 hours of frozen reference, run down in 4 seconds; the reopen lands on the last beat.
const DUR = 2 * BAR;
const END = DUR - BEAT;

export const Clock: React.FC = () => {
  const frame = useCurrentFrame();
  const left = interpolate(frame, [4, END], [48 * 3600, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  const s = Math.floor(left);
  const hms = `${String(Math.floor(s / 3600)).padStart(2, "0")}:${String(Math.floor(s / 60) % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  const open = frame >= END;
  const pop = useSpring(0, 13);
  const reopen = useSpring(END, 10, 0.5);
  const out = useExit(DUR, 5);
  return (
    <Stage glowX={50} glowY={45} glow={open ? 0.4 : 0.16}>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", opacity: out }}>
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 16,
            font: `600 30px ${MONO}`,
            letterSpacing: 4,
            padding: "14px 26px",
            borderRadius: 999,
            border: `2px solid ${open ? C.accent : C.line}`,
            background: open ? C.accent : C.surface,
            color: open ? C.ink : C.fg,
            scale: String(open ? 0.9 + 0.1 * reopen : 0.9 + 0.1 * pop),
          }}
        >
          <span style={{ width: 14, height: 14, borderRadius: 7, background: open ? C.ink : C.fg }} />
          {open ? "REFERENCE REOPENS" : "REFERENCE FROZEN"}
        </div>
        <div
          style={{
            marginTop: 36,
            font: `600 300px ${MONO}`,
            letterSpacing: "-0.06em",
            fontVariantNumeric: "tabular-nums",
            color: open ? C.accent : C.fg,
            scale: String(open ? 1 + 0.06 * (1 - reopen) : 0.94 + 0.06 * pop),
          }}
        >
          {hms}
        </div>
        <div style={{ marginTop: 26, fontSize: 46, fontWeight: 500, color: C.muted, letterSpacing: "-0.01em", opacity: ramp(frame, 10, 22) }}>
          Friday 20:00 to Sunday 20:00 ET. Every weekend, every holiday.
        </div>
      </AbsoluteFill>
    </Stage>
  );
};
