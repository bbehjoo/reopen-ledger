"""Soundtrack for the Reopen Ledger launch video, synthesised from scratch (no samples, no third-party audio).

    uv run --with numpy --with scipy python video/music/make_track.py   ->  video/public/track.wav

120 BPM, A minor (Am F C G), 25 bars = 50 s, laid out on the same bar grid as the video (src/timing.ts):
bars 0-1 ticking clock, 2 impact + groove in, 4 hats, 6 claps, 9-20 arpeggio, 21-22 stabs, 23-24 outro.
"""
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

SR = 48000
BPM = 120
BEAT = 60 / BPM
BAR = 4 * BEAT
BARS = 25
N = int(BARS * BAR * SR)
rng = np.random.default_rng(7)

L = np.zeros(N)
R = np.zeros(N)
SEND = np.zeros(N)  # mono reverb send


def t_of(bar, beat=0.0):
    return (bar * 4 + beat) * BEAT


def place(sig, at, gain=1.0, pan=0.0, send=0.0):
    i = int(at * SR)
    if i >= N:
        return
    sig = sig[: N - i]
    lg, rg = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    L[i:i + len(sig)] += sig * gain * lg * 1.414
    R[i:i + len(sig)] += sig * gain * rg * 1.414
    if send:
        SEND[i:i + len(sig)] += sig * gain * send


def env(n, a=0.005, d=0.2):
    t = np.arange(n) / SR
    e = np.minimum(t / max(a, 1e-4), 1.0) * np.exp(-np.maximum(t - a, 0) / d)
    return e


def lp(x, f, order=2):
    return sosfilt(butter(order, min(f, SR / 2 - 100), "low", fs=SR, output="sos"), x)


def hp(x, f, order=2):
    return sosfilt(butter(order, f, "high", fs=SR, output="sos"), x)


def bp(x, lo, hi):
    return sosfilt(butter(2, [lo, hi], "band", fs=SR, output="sos"), x)


def saw(freq, dur, detune=0.0):
    t = np.arange(int(dur * SR)) / SR
    ph = (t * freq * (1 + detune)) % 1.0
    return 2 * ph - 1


def note(n):  # midi -> Hz
    return 440 * 2 ** ((n - 69) / 12)


# --- instruments
def kick():
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    f = 45 + 95 * np.exp(-t / 0.035)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t / 0.28)
    click = hp(rng.standard_normal(n), 2500) * np.exp(-t / 0.004) * 0.25
    return np.tanh(1.6 * (body + click))


def hat(dec=0.035):
    n = int(0.12 * SR)
    return hp(rng.standard_normal(n), 7500) * env(n, 0.001, dec) * 0.5


def clap():
    n = int(0.35 * SR)
    noise = bp(rng.standard_normal(n), 900, 4200)
    e = np.zeros(n)
    for k, off in enumerate((0, 0.011, 0.022)):
        i = int(off * SR)
        e[i:] += env(n - i, 0.001, 0.012 if k < 2 else 0.12)
    t = np.arange(n) / SR
    tone = np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.05) * 0.3
    return noise * e * 0.7 + tone


def tick(hi=True):
    n = int(0.06 * SR)
    t = np.arange(n) / SR
    f = 3200 if hi else 2400
    return (np.sin(2 * np.pi * f * t) * np.exp(-t / 0.008) + bp(rng.standard_normal(n), 2000, 6000) * np.exp(-t / 0.004) * 0.4) * 0.6


def impact(dur=3.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    boom = np.sin(2 * np.pi * (38 + 40 * np.exp(-t / 0.08)) * t) * np.exp(-t / 0.9)
    noise = lp(rng.standard_normal(n), 2500) * np.exp(-t / 0.25) * 0.5
    return np.tanh(1.4 * (boom + noise))


def riser(dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = rng.standard_normal(n)
    out = np.zeros(n)
    blocks = 64
    for b in range(blocks):  # rising band-pass sweep, block-wise
        s, e = b * n // blocks, (b + 1) * n // blocks
        fc = 300 * (40 ** (b / blocks))
        out[s:e] = bp(x[max(0, s - 2000):e], fc * 0.7, min(fc * 1.4, SR / 2 - 200))[-(e - s):]
    return out * (t / dur) ** 2 * 0.5


def pad_chord(notes, dur, cutoff=1400):
    n = int(dur * SR)
    sig = np.zeros(n)
    for m in notes:
        for d in (-0.004, 0.0, 0.0045):
            sig += saw(note(m), dur, d)
    sig = lp(sig / (3 * len(notes)), cutoff, 2)
    a = np.minimum(np.arange(n) / (0.35 * SR), 1.0)
    rel = np.minimum((n - np.arange(n)) / (0.25 * SR), 1.0)
    return sig * a * rel


def pluck(m, dur=0.22):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = (saw(note(m), dur) + 0.5 * np.sign(np.sin(2 * np.pi * note(m) * 2 * t)))
    return lp(x, 3200) * np.exp(-t / 0.07) * 0.5


def bass(m, dur):
    n = int(dur * SR)
    x = saw(note(m), dur) + 0.6 * np.sin(2 * np.pi * note(m - 12) * np.arange(n) / SR)
    return lp(x, 420, 3) * env(n, 0.004, dur * 0.6) * 0.9


def stab(notes):
    return pad_chord(notes, 0.5, 2600) * env(int(0.5 * SR), 0.003, 0.18) * 2.2


# --- arrangement
CHORDS = [(57, [57, 60, 64, 69], 45), (53, [53, 57, 60, 65], 41), (48, [48, 52, 55, 60], 36), (55, [55, 59, 62, 67], 43)]
kick_times = []

for bar in range(BARS):
    root, ch, bnote = CHORDS[bar % 4]
    groove = 2 <= bar <= 20
    # pad, every bar (quieter in intro, brighter mid-section)
    cut = 900 if bar < 2 else (1300 if bar < 9 else 2000)
    if bar < 23:
        place(pad_chord([m - 12 for m in ch], BAR + 0.1, cut), t_of(bar), 0.22 if bar >= 2 else 0.14, 0.0, 0.35)
    if bar < 2:  # ticking clock
        for b in range(4):
            place(tick(b % 2 == 0), t_of(bar, b), 0.5, 0.25 if b % 2 else -0.25, 0.2)
        continue
    if groove:
        for b in range(4):
            place(kick(), t_of(bar, b), 0.9)
            kick_times.append(t_of(bar, b))
            place(bass(bnote, BEAT * 0.45), t_of(bar, b + 0.5), 0.55)
        if bar >= 4:
            for b in range(4):
                place(hat(), t_of(bar, b + 0.5), 0.35, 0.3)
            if bar >= 9:
                for b in range(16):
                    if b % 4 != 2:
                        place(hat(0.015), t_of(bar, b / 4), 0.12, -0.3)
        if bar >= 6:
            for b in (1, 3):
                place(clap(), t_of(bar, b), 0.45, 0.0, 0.3)
        if 9 <= bar <= 20:
            arp = [ch[0] + 12, ch[1] + 12, ch[2] + 12, ch[3] + 12, ch[2] + 12, ch[1] + 12, ch[3] + 12, ch[2] + 12]
            for k in range(16):
                place(pluck(arp[k % 8]), t_of(bar, k / 4), 0.16, 0.5 if k % 2 else -0.5, 0.45)
    if bar in (21, 22):  # stabs on the trust words
        for b in (0, 2):
            place(stab(ch), t_of(bar, b), 0.5, 0.0, 0.5)
            place(kick(), t_of(bar, b), 0.7)
            kick_times.append(t_of(bar, b))

# impacts and risers
place(riser(BAR), t_of(1), 0.6, 0.0, 0.3)
place(impact(), t_of(2), 0.9, 0.0, 0.4)
place(riser(BAR), t_of(8), 0.35, 0.0, 0.3)
place(riser(BAR), t_of(14), 0.35, 0.0, 0.3)
place(riser(BAR), t_of(20), 0.5, 0.0, 0.3)
place(impact(4.0), t_of(23), 0.95, 0.0, 0.5)
place(pad_chord([45, 52, 57, 60, 64], 4.0, 1100), t_of(23), 0.3, 0.0, 0.6)

# sidechain: duck everything but the kick-bearing beats themselves (approximation: duck the whole bus, then re-add punch)
duck = np.ones(N)
tt = np.arange(N) / SR
for k in kick_times:
    i = int(k * SR)
    j = min(N, i + int(0.3 * SR))
    duck[i:j] = np.minimum(duck[i:j], 1 - 0.5 * np.exp(-(tt[i:j] - k) / 0.09))

# reverb: exponentially decaying stereo noise impulse
ir_n = int(1.8 * SR)
irt = np.arange(ir_n) / SR
irL = rng.standard_normal(ir_n) * np.exp(-irt / 0.45)
irR = rng.standard_normal(ir_n) * np.exp(-irt / 0.45)
send = lp(hp(SEND, 300), 6000)
spec = np.fft.rfft(send, 2 ** int(np.ceil(np.log2(N + ir_n))))
revL = np.fft.irfft(spec * np.fft.rfft(irL, len(spec) * 2 - 2))[:N]
revR = np.fft.irfft(spec * np.fft.rfft(irR, len(spec) * 2 - 2))[:N]
revL *= 0.12 / (np.abs(revL).max() + 1e-9) * np.abs(send).max()
revR *= 0.12 / (np.abs(revR).max() + 1e-9) * np.abs(send).max()

mixL = (L + revL) * duck
mixR = (R + revR) * duck
# fade the tail, gentle glue, normalise
fade = np.minimum(1.0, (N - np.arange(N)) / (1.5 * SR))
mixL, mixR = mixL * fade, mixR * fade
peak = max(np.abs(mixL).max(), np.abs(mixR).max())
mixL, mixR = np.tanh(1.3 * mixL / peak) / np.tanh(1.3), np.tanh(1.3 * mixR / peak) / np.tanh(1.3)
mixL, mixR = mixL * 0.89, mixR * 0.89

out = Path(__file__).resolve().parents[1] / "public" / "track.wav"
out.parent.mkdir(parents=True, exist_ok=True)
pcm = (np.stack([mixL, mixR], axis=1) * 32767).astype("<i2")
import wave  # noqa: E402

with wave.open(str(out), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print(out, f"{N / SR:.1f} s")
