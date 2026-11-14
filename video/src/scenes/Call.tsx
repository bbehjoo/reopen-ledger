import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import data from "../data.json";
import { BAR, BEAT, C, MONO, ramp, Slam, Stage, useExit } from "../kit";

// Bars 18-20: the action. The code types itself; chips land on beats.
type Tok = [string, string];
const short = (a: string) => `${a.slice(0, 6)}...${a.slice(-4)}`;
const CODE: Tok[][] = [
  [["c", "// one transaction, no value"]],
  [["k", "await "], ["p", "commitCalls({"]],
  [["p", "  wallet,"]],
  [["p", "  ledger: "], ["s", `"${short(data.ledger ?? "0x")}"`], ["p", ","]],
  [["p", "  windowId: windowId("], ["n", "1"], ["p", ", "], ["s", '"2026-11-20"'], ["p", "),"]],
  [["p", "  calls: [{ token: NVDAc, p: "], ["n", "0.62"], ["p", " },"]],
  [["p", "          { token: TSLAc, p: "], ["n", "0.41"], ["p", " }],"]],
  [["p", "});"]],
];
const COL: Record<string, string> = { c: "#636973", k: "#ff8a57", p: "#eef0f2", s: "#57d39a", n: "#ff8a57" };

export const Call: React.FC = () => {
  const frame = useCurrentFrame();
  const out = useExit(3 * BAR, 6);
  const total = CODE.flat().reduce((n, [, t]) => n + t.length, 0);
  const shown = Math.floor(ramp(frame, BEAT, 2 * BAR, 0, total, (x) => x));
  let left = shown;
  return (
    <Stage glowX={20} glowY={30} glow={0.24}>
      <AbsoluteFill style={{ padding: "130px 110px", flexDirection: "row", gap: 80, alignItems: "center", opacity: out }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 132, fontWeight: 700, letterSpacing: "-0.055em", lineHeight: 0.98 }}>
            <Slam at={0}>Call the</Slam>
            <br />
            <Slam at={6} color={C.accent}>reopen.</Slam>
          </div>
          <div style={{ fontSize: 44, color: C.muted, lineHeight: 1.3, marginTop: 40, maxWidth: 760, opacity: ramp(frame, BEAT, BEAT + 10) }}>
            A probability per token, on the record before the cutoff. Scored against Chainlink when the price comes back.
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 16, marginTop: 44 }}>
            {["Holds no funds", "Humans and agents", `Builder Code ${data.builder_code ?? ""}`].map((t, i) => (
              <span
                key={t}
                style={{
                  font: `500 28px ${MONO}`,
                  padding: "14px 22px",
                  borderRadius: 999,
                  border: `1px solid ${C.line}`,
                  background: C.surface,
                  opacity: ramp(frame, BAR + i * BEAT, BAR + i * BEAT + 6),
                  translate: `0 ${(1 - ramp(frame, BAR + i * BEAT, BAR + i * BEAT + 10)) * 20}px`,
                }}
              >
                {t}
              </span>
            ))}
          </div>
        </div>
        <div
          style={{
            width: 860,
            background: "#101215",
            border: `1px solid ${C.line}`,
            borderRadius: 28,
            padding: "38px 40px",
            font: `500 30px/1.7 ${MONO}`,
            whiteSpace: "pre",
            opacity: ramp(frame, 4, 14),
            boxShadow: "0 50px 100px -40px rgba(0,0,0,0.8)",
          }}
        >
          {CODE.map((line, li) => (
            <div key={li} style={{ minHeight: 51 }}>
              {line.map(([k, t], ti) => {
                const n = Math.max(0, Math.min(t.length, left));
                left -= t.length;
                return (
                  <span key={ti} style={{ color: COL[k] }}>
                    {t.slice(0, n)}
                  </span>
                );
              })}
            </div>
          ))}
          <span style={{ display: "inline-block", width: 16, height: 34, background: C.accent, opacity: Math.floor(frame / 8) % 2 ? 1 : 0.2 }} />
        </div>
      </AbsoluteFill>
    </Stage>
  );
};
