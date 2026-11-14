import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { BAR, C, MONO, ramp, Slam, Stage, useExit } from "../kit";

// Bars 15-17: the real site, captured from the build, scrolling inside a browser frame.
const IMG_W = 1920;
const IMG_H = 5600;

export const Product: React.FC = () => {
  const frame = useCurrentFrame();
  const out = useExit(3 * BAR, 6);
  const FW = 1460;
  const scale = FW / IMG_W;
  const enter = ramp(frame, 0, 26);
  const scroll = interpolate(frame, [20, 3 * BAR - 6], [0, -(IMG_H * scale - 760)], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  return (
    <Stage glowX={50} glowY={0} glow={0.26}>
      <AbsoluteFill style={{ alignItems: "center", paddingTop: 70, opacity: out }}>
        <div style={{ fontSize: 76, fontWeight: 700, letterSpacing: "-0.045em" }}>
          <Slam at={0}>Live on Base.</Slam> <Slam at={8} color={C.accent}>Updated every day.</Slam>
        </div>
        <div
          style={{
            marginTop: 50,
            width: FW,
            height: 800,
            borderRadius: 26,
            overflow: "hidden",
            border: `1px solid rgba(255,255,255,0.14)`,
            background: C.surface,
            boxShadow: "0 60px 120px -40px rgba(0,0,0,0.8), 0 0 0 1px rgba(255,255,255,0.04) inset",
            transform: `perspective(2200px) rotateX(${(1 - enter) * 24}deg) translateY(${(1 - enter) * 160}px)`,
            transformOrigin: "50% 0%",
            opacity: enter,
          }}
        >
          <div style={{ height: 64, display: "flex", alignItems: "center", gap: 12, padding: "0 24px", borderBottom: `1px solid ${C.line}`, background: C.surface2 }}>
            {["#ff5f57", "#febc2e", "#28c840"].map((c) => (
              <span key={c} style={{ width: 16, height: 16, borderRadius: 8, background: c, opacity: 0.85 }} />
            ))}
            <div style={{ marginLeft: 26, flex: 1, height: 38, borderRadius: 19, background: C.bg, display: "flex", alignItems: "center", padding: "0 20px", font: `500 22px ${MONO}`, color: C.muted }}>
              bbehjoo.github.io/reopen-ledger
            </div>
          </div>
          <div style={{ position: "relative", height: 736, overflow: "hidden" }}>
            <Img src={staticFile("site-full.png")} style={{ position: "absolute", left: 0, top: scroll, width: FW, height: IMG_H * scale }} />
          </div>
        </div>
      </AbsoluteFill>
    </Stage>
  );
};
