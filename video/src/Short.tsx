import React from "react";
import { AbsoluteFill, Composition, Img, interpolate, Sequence, Series, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Audio } from "@remotion/media";
import data from "./short.json";
import { BAR, BEAT, C, Mark, MONO, ramp, Slam, Stage, useExit, useSpring } from "./kit";

// 10 bars at 120 BPM = 20 s. Audio: the launch track from bar 1 (riser, impact on bar 2 = frame 60) for 8 bars,
// then its closing impact and tail (track bars 23-24) under the call to action. Every number comes from
// data/make_short.py (src/short.json and public/card.png).
const POS = "#57d39a";
const short = (h: string) => `${h.slice(0, 6)}...${h.slice(-4)}`;
const called = (c: { p: number; o: number }) => c.p !== 0.5 && (c.p > 0.5) === (c.o === 1);

/** Bars 0-1: what is frozen, and the job. */
const Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const out = useExit(2 * BAR, 6);
  return (
    <Stage glowX={78} glowY={18} glow={frame < BAR ? 0.12 : 0.26}>
      <AbsoluteFill style={{ padding: "150px 120px", opacity: out }}>
        <div style={{ fontSize: 112, fontWeight: 700, letterSpacing: "-0.05em", lineHeight: 1.02 }}>
          <Slam at={0}>Stock</Slam> <Slam at={4}>tokens</Slam> <Slam at={8}>trade</Slam> <Slam at={12}>all</Slam>{" "}
          <Slam at={16}>weekend.</Slam>
          <br />
          <Slam at={BAR - 14} style={{ color: C.muted }}>The price lenders use is</Slam>{" "}
          <Slam at={BAR} color={C.accent}>
            frozen.
          </Slam>
        </div>
        <div
          style={{
            marginTop: 70,
            display: "inline-flex",
            alignSelf: "flex-start",
            alignItems: "center",
            gap: 18,
            padding: "22px 34px",
            borderRadius: 999,
            background: C.accent,
            color: C.ink,
            fontSize: 52,
            fontWeight: 650,
            letterSpacing: "-0.02em",
            opacity: ramp(frame, BAR + BEAT, BAR + BEAT + 6),
            translate: `0 ${(1 - ramp(frame, BAR + BEAT, BAR + BEAT + 12)) * 30}px`,
          }}
        >
          Call where it reopens. Get scored on chain.
        </div>
      </AbsoluteFill>
      <AbsoluteFill
        style={{ backgroundColor: "#fff", opacity: interpolate(frame, [BAR, BAR + 5], [0.5, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) * (frame >= BAR ? 1 : 0) }}
      />
    </Stage>
  );
};

/** Bars 2-5: the commit (real record), then the reopen scores each call. */
const Record: React.FC = () => {
  const frame = useCurrentFrame();
  const REOPEN = 2 * BAR;
  const out = useExit(4 * BAR, 6);
  const after = frame >= REOPEN;
  const status =
    frame < REOPEN - 24 ? "OPEN  /  closes Sun 18:00 ET" : frame < REOPEN ? "SEALED  /  on Base" : "REOPEN  /  Sun 20:00 ET, Chainlink";
  return (
    <Stage glowX={after ? 82 : 18} glowY={20} glow={0.22}>
      <AbsoluteFill style={{ padding: "96px 120px", opacity: out }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div style={{ fontSize: 88, fontWeight: 700, letterSpacing: "-0.05em", lineHeight: 1.02 }}>
            {after ? (
              <>
                <Slam at={REOPEN}>The price comes back.</Slam>
                <br />
                <Slam at={REOPEN + 8} color={C.accent}>
                  Chainlink scores every call.
                </Slam>
              </>
            ) : (
              <>
                <Slam at={0}>Agents put their odds</Slam>
                <br />
                <Slam at={6} color={C.accent}>
                  on chain. Sealed.
                </Slam>
              </>
            )}
          </div>
          <div
            style={{
              font: `600 26px ${MONO}`,
              letterSpacing: 2,
              padding: "14px 22px",
              borderRadius: 999,
              border: `1px solid ${frame < REOPEN - 24 ? C.line : C.accent}`,
              color: frame < REOPEN - 24 ? C.muted : C.accentText,
              background: C.surface,
              marginTop: 18,
              whiteSpace: "nowrap",
            }}
          >
            {status}
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 22, marginTop: 64 }}>
          {data.calls.map((c, i) => {
            const at = 10 + i * 3;
            const rv = REOPEN + 14 + i * 4;
            const shown = frame >= rv;
            const hit = called(c);
            const s = ramp(frame, at, at + 10);
            return (
              <div
                key={c.s}
                style={{
                  height: 128,
                  borderRadius: 22,
                  padding: "20px 26px",
                  background: shown && hit ? "rgba(87,211,154,0.10)" : C.surface,
                  border: `1px solid ${shown ? (hit ? POS : C.line) : C.line}`,
                  opacity: s * (shown && !hit ? 0.5 : 1),
                  translate: `0 ${(1 - s) * 26}px`,
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <div>
                  <div style={{ fontSize: 38, fontWeight: 650, letterSpacing: "-0.02em" }}>{c.s}</div>
                  <div style={{ font: `500 26px ${MONO}`, color: C.muted, marginTop: 6 }}>
                    {c.p >= 0.5 ? `Higher ${Math.round(c.p * 100)}%` : `Lower ${Math.round((1 - c.p) * 100)}%`}
                  </div>
                </div>
                {shown && (
                  <div
                    style={{
                      font: `600 24px ${MONO}`,
                      color: hit ? POS : C.dim,
                      scale: String(0.7 + 0.3 * ramp(frame, rv, rv + 6)),
                    }}
                  >
                    {hit ? "CALLED" : "MISSED"}
                  </div>
                )}
              </div>
            );
          })}
        </div>
        <div style={{ marginTop: 40, font: `500 26px ${MONO}`, color: C.dim, display: "flex", justifyContent: "space-between" }}>
          <span style={{ opacity: ramp(frame, 40, 50) }}>
            Weekend DEX  /  tx {short(data.tx)}  /  block {data.block?.toLocaleString("en-US")}  /  Builder Code {data.builder_code}
          </span>
          <span style={{ color: C.fg, font: `600 34px ${MONO}`, opacity: ramp(frame, REOPEN + 14, REOPEN + 24) }}>
            {data.calls.filter((c, i) => frame >= REOPEN + 14 + i * 4 && called(c)).length} of {data.decided} called
          </span>
        </div>
      </AbsoluteFill>
    </Stage>
  );
};

/** Bars 6-7: the real result card. */
const Card: React.FC = () => {
  const frame = useCurrentFrame();
  const s = useSpring(0, 15, 0.7);
  const out = useExit(2 * BAR, 6);
  const W = 1360;
  const k = W / 1200;
  const push = 1 + 0.05 * ramp(frame, 0, 2 * BAR, 0, 1, (x) => x);
  const ring = (x: number, y: number, w: number, h: number, at: number, color: string) => (
    <div
      style={{
        position: "absolute",
        left: x * k - 14,
        top: y * k - 10,
        width: w * k + 28,
        height: h * k + 20,
        borderRadius: 14,
        border: `3px solid ${color}`,
        boxShadow: `0 0 40px ${color}55`,
        opacity: ramp(frame, at, at + 6),
        scale: String(1.15 - 0.15 * ramp(frame, at, at + 10)),
      }}
    />
  );
  return (
    <Stage glowX={50} glowY={10} glow={0.18}>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", opacity: out }}>
        <div
          style={{
            position: "relative",
            width: W,
            height: 675 * k,
            scale: String((0.86 + 0.14 * s) * push),
            rotate: `${(1 - s) * -2}deg`,
            borderRadius: 28,
            overflow: "hidden",
            border: `1px solid ${C.line}`,
            boxShadow: "0 60px 120px -40px rgba(0,0,0,0.9)",
          }}
        >
          <Img src={staticFile("card.png")} style={{ width: W, height: 675 * k, display: "block" }} />
          {ring(552, 312, 150, 36, 30, C.accent)}
          {ring(752, 312, 120, 36, 34, C.accent)}
          {ring(752, 366, 120, 36, 52, C.dim)}
        </div>
        <div style={{ marginTop: 34, font: `500 30px ${MONO}`, color: C.muted, opacity: ramp(frame, 20, 30) }}>
          Real result, {data.when}. Lower score is better.
        </div>
      </AbsoluteFill>
    </Stage>
  );
};

/** Bars 8-9: the ask. */
const Ask: React.FC = () => {
  const frame = useCurrentFrame();
  const s = useSpring(0, 12, 0.6);
  const flash = interpolate(frame, [0, 5], [0.8, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const fade = ramp(frame, 2 * BAR - 14, 2 * BAR, 1, 0);
  return (
    <Stage glowX={50} glowY={40} glow={0.32}>
      <AbsoluteFill style={{ padding: "0 120px", justifyContent: "center", opacity: fade }}>
        <div style={{ fontSize: 150, fontWeight: 700, letterSpacing: "-0.055em", lineHeight: 0.98, scale: String(0.92 + 0.08 * s), transformOrigin: "left center" }}>
          Can your agent
          <br />
          <span style={{ color: C.accent }}>beat it?</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 26, marginTop: 64, opacity: ramp(frame, 10, 18) }}>
          <Mark size={72} />
          <span style={{ fontSize: 60, fontWeight: 700, letterSpacing: "-0.04em" }}>Reopen Ledger</span>
          <span style={{ font: `500 40px ${MONO}`, color: C.fg, marginLeft: 24 }}>bbehjoo.github.io/reopen-ledger</span>
        </div>
        <div style={{ marginTop: 26, font: `500 32px ${MONO}`, color: C.muted, opacity: ramp(frame, 20, 28) }}>
          Template: github.com/bbehjoo/reopen-ledger-agent  /  next cutoff Sun 18:00 ET
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ backgroundColor: "#fff", opacity: flash }} />
    </Stage>
  );
};

export const Short20: React.FC = () => {
  const { fps } = useVideoConfig();
  return (
    <>
      <Series>
        <Series.Sequence name="Hook" durationInFrames={2 * BAR} premountFor={fps}>
          <Hook />
        </Series.Sequence>
        <Series.Sequence name="Record" durationInFrames={4 * BAR} premountFor={fps}>
          <Record />
        </Series.Sequence>
        <Series.Sequence name="Card" durationInFrames={2 * BAR} premountFor={fps}>
          <Card />
        </Series.Sequence>
        <Series.Sequence name="Ask" durationInFrames={2 * BAR} premountFor={fps}>
          <Ask />
        </Series.Sequence>
      </Series>
      <Sequence durationInFrames={8 * BAR}>
        <Audio src={staticFile("track.wav")} trimBefore={BAR} />
      </Sequence>
      <Sequence from={8 * BAR} durationInFrames={2 * BAR}>
        <Audio src={staticFile("track.wav")} trimBefore={23 * BAR} />
      </Sequence>
    </>
  );
};

export const ShortComposition = () => (
  <Composition id="Short20" component={Short20} durationInFrames={10 * BAR} fps={30} width={1920} height={1080} />
);
