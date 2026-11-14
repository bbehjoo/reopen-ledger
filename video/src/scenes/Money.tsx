import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import data from "../data.json";
import { BAR, BEAT, C, Count, MONO, ramp, Slam, Stage, useExit } from "../kit";

// Bars 6-8: the debt that sits on a frozen price, then where it lands.
const TURN = 2 * BAR;

export const Money: React.FC = () => {
  const frame = useCurrentFrame();
  const wipe = ramp(frame, 0, 12);
  const out = useExit(3 * BAR, 6);
  if (frame < TURN) {
    return (
      <AbsoluteFill style={{ backgroundColor: C.bg, overflow: "hidden" }}>
        <AbsoluteFill
          style={{
            translate: `0 ${(1 - wipe) * 100}%`,
            background: `radial-gradient(120% 90% at 100% 0%, #ffb48f 0%, ${C.accent} 45%, #a83a0c 100%)`,
            color: C.ink,
            padding: "130px 120px",
            fontFamily: "Geist, sans-serif",
          }}
        >
          <div style={{ font: `600 34px ${MONO}`, letterSpacing: 3, opacity: ramp(frame, 8, 16) }}>
            BORROWED AGAINST STOCK TOKENS ON BASE
          </div>
          <div style={{ fontSize: 330, fontWeight: 700, letterSpacing: "-0.06em", lineHeight: 1, marginTop: 40 }}>
            <Count a={8} b={56} to={data.debt_usd / 1e6} fmt={(v) => `$${v.toFixed(2)}`} />
            <span style={{ fontSize: 150, opacity: 0.7 }}>M</span>
          </div>
          <div style={{ fontSize: 54, fontWeight: 600, letterSpacing: "-0.02em", marginTop: 40, maxWidth: 1400, opacity: ramp(frame, BAR, BAR + 10) }}>
            USDC lent on Aave and Morpho by {data.borrowers} borrowers, against {`$${(data.collateral_usd / 1e6).toFixed(1)}M`} of tokenized stock.
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }
  const f = frame - TURN;
  return (
    <Stage glowX={30} glowY={70} glow={0.2}>
      <AbsoluteFill style={{ justifyContent: "center", padding: "0 130px", opacity: out }}>
        <div style={{ fontSize: 112, fontWeight: 700, letterSpacing: "-0.05em", lineHeight: 1.02 }}>
          <Slam at={TURN}>Nothing liquidates</Slam>
          <br />
          <Slam at={TURN + 4}>while the price is frozen.</Slam>
        </div>
        <div style={{ fontSize: 112, fontWeight: 700, letterSpacing: "-0.05em", lineHeight: 1.02, marginTop: 40 }}>
          <Slam at={TURN + 2 * BEAT} color={C.accent}>
            It all lands at the reopen.
          </Slam>
        </div>
        <div style={{ height: 6, marginTop: 70, background: C.accent, width: `${ramp(f, 2 * BEAT, 4 * BEAT - 4) * 100}%`, borderRadius: 3 }} />
      </AbsoluteFill>
    </Stage>
  );
};
