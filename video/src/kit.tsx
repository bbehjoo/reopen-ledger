import React from "react";
import { AbsoluteFill, Easing, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/fonts";

loadFont({ family: "Geist", url: staticFile("Geist-Variable.woff2"), weight: "100 900" });
loadFont({ family: "Geist Mono", url: staticFile("GeistMono-Variable.woff2"), weight: "100 900" });

// The grid the music is written on (music/make_track.py): 120 BPM at 30 fps.
export const BEAT = 15;
export const BAR = 60;

export const C = {
  bg: "#0b0c0e",
  surface: "#14161a",
  surface2: "#1a1d22",
  line: "rgba(255,255,255,0.10)",
  fg: "#eef0f2",
  muted: "#9298a2",
  dim: "#636973",
  accent: "#ff6a2b",
  accentText: "#ff8a57",
  ink: "#160a04",
};
export const SANS = "Geist, system-ui, sans-serif";
export const MONO = "'Geist Mono', ui-monospace, monospace";
export const EASE = Easing.bezier(0.16, 1, 0.3, 1);

export const ramp = (f: number, a: number, b: number, from = 0, to = 1, easing = EASE) =>
  interpolate(f, [a, b], [from, to], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing });

/** spring from frame `at`, 0 -> 1 */
export const useSpring = (at: number, damping = 14, mass = 0.6) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: frame - at, fps, config: { damping, mass, stiffness: 160 } });
};

const GRAIN =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='220' height='220'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")";

/** Dark stage: off-black, one drifting orange glow, grain and a vignette. */
export const Stage: React.FC<{ glowX?: number; glowY?: number; glow?: number; children?: React.ReactNode }> = ({
  glowX = 75,
  glowY = 20,
  glow = 0.22,
  children,
}) => {
  const frame = useCurrentFrame();
  const drift = Math.sin(frame / 50) * 3;
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg, fontFamily: SANS, color: C.fg, overflow: "hidden" }}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(900px 700px at ${glowX + drift}% ${glowY - drift}%, rgba(255,106,43,${glow}), transparent 70%)`,
        }}
      />
      {children}
      <AbsoluteFill style={{ backgroundImage: GRAIN, opacity: 0.06, mixBlendMode: "overlay", pointerEvents: "none" }} />
      <AbsoluteFill
        style={{ background: "radial-gradient(120% 90% at 50% 50%, transparent 55%, rgba(0,0,0,0.55) 100%)", pointerEvents: "none" }}
      />
    </AbsoluteFill>
  );
};

/** A word that lands: rises, unblurs and settles with a spring at frame `at`. */
export const Slam: React.FC<{ at: number; children: React.ReactNode; color?: string; style?: React.CSSProperties }> = ({
  at,
  children,
  color,
  style,
}) => {
  const frame = useCurrentFrame();
  const s = useSpring(at, 12, 0.5);
  if (frame < at) return <span style={{ opacity: 0, ...style }}>{children}</span>;
  return (
    <span
      style={{
        display: "inline-block",
        color,
        opacity: ramp(frame, at, at + 4),
        translate: `0 ${(1 - s) * 60}px`,
        scale: String(0.9 + 0.1 * s),
        filter: `blur(${ramp(frame, at, at + 6, 14, 0)}px)`,
        ...style,
      }}
    >
      {children}
    </span>
  );
};

/** Fades a whole scene out over its last frames. */
export const useExit = (dur: number, len = 8) => {
  const frame = useCurrentFrame();
  return ramp(frame, dur - len, dur, 1, 0, Easing.in(Easing.quad));
};

export const usd = (v: number, digits = 2) =>
  v >= 1e6 ? `$${(v / 1e6).toFixed(digits)}M` : v >= 1e3 ? `$${(v / 1e3).toFixed(0)}k` : `$${Math.round(v)}`;

/** A number counting up between frames a and b. */
export const Count: React.FC<{ a: number; b: number; to: number; fmt: (v: number) => string; style?: React.CSSProperties }> = ({
  a,
  b,
  to,
  fmt,
  style,
}) => {
  const frame = useCurrentFrame();
  const v = ramp(frame, a, b, 0, to, Easing.out(Easing.cubic));
  return <span style={{ fontVariantNumeric: "tabular-nums", ...style }}>{fmt(v)}</span>;
};

export const Mark: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 32 32">
    <rect width="32" height="32" rx="9" fill={C.accent} />
    <path d="M7 19.5h10.5L25 10.5" fill="none" stroke={C.ink} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx="25" cy="10.5" r="2.6" fill={C.ink} />
  </svg>
);
