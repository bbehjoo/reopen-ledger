"""Demo video for the submission post: captures the live site with headless Edge, then renders a 1280x720
captioned walk-through with ffmpeg (about 70 s, no audio).

    uv run python scripts/demo_video.py [out.mp4]

Needs Microsoft Edge (or set EDGE to a Chromium binary) and ffmpeg on PATH. Nothing is posted.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SITE = "https://bbehjoo.github.io/reopen-ledger/"
EDGE = os.environ.get("EDGE", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
V = Path(tempfile.mkdtemp(prefix="reopen-demo-"))
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "reopen-ledger-demo.mp4"


def capture(page):
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={V / ('p-' + page)}",
                    "--hide-scrollbars", "--force-device-scale-factor=1", "--window-size=1280,2600",
                    "--virtual-time-budget=10000", f"--screenshot={V / (page + '.png')}", f"{SITE}{page}.html"],
                   capture_output=True, check=False)
FONT = "C\\:/Windows/Fonts/segoeui.ttf"
BOLD = "C\\:/Windows/Fonts/segoeuib.ttf"
W, H, FPS = 1280, 720, 30

CARD = [  # (seconds, title, subtitle)
    (5, "Reopen Ledger", "Coinbase's tokenized stocks trade all weekend on Base.\nTheir reference price is frozen from Friday 20:00 to Sunday 20:00 ET."),
]
SCENES = [  # (page, y0, y1, seconds, caption)
    ("index", 0, 230, 9, "Every day, from Base chain logs: what these markets can absorb"),
    ("absorb", 0, 500, 11, "Pool depth below the price, set against what Aave V4 and Morpho\nwould liquidate if the reference reopened 5%, 10% or 20% lower"),
    ("tape", 0, 700, 11, "The weekend tape: how far the token pools drift from the frozen reference,\nand how close the weekend DEX price comes to the reopen. Every weekend since Aug 24"),
    ("commit", 0, 200, 11, "Put a call on the record: one transaction, a probability per token.\nThe contract holds no funds; nothing is traded. Agents use one function"),
    ("board", 0, 150, 9, "Scored against the Chainlink feed after the window closes:\nskill against the weekend DEX price and against 50%"),
    ("data", 0, 300, 9, "Every export is signed, its hash goes on chain, and every number\nreplays from public chain logs. Measurements, not verdicts"),
]
END = (6, "bbehjoo.github.io/reopen-ledger", "Code and data: github.com/bbehjoo/reopen-ledger")


def run(args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)


def card(i, secs, title, sub):
    (V / f"t{i}.txt").write_text(title, encoding="utf-8", newline="\n")
    (V / f"s{i}.txt").write_text(sub, encoding="utf-8", newline="\n")
    vf = (f"drawtext=expansion=none:fontfile='{BOLD}':textfile='{(V / f't{i}.txt').as_posix().replace(':', chr(92) + ':')}':"
          f"fontsize=64:fontcolor=0x1c1b19:x=(w-text_w)/2:y=h/2-110,"
          f"drawtext=expansion=none:fontfile='{FONT}':textfile='{(V / f's{i}.txt').as_posix().replace(':', chr(92) + ':')}':"
          f"fontsize=30:fontcolor=0x6b675f:line_spacing=4:x=(w-text_w)/2:y=h/2+10,"
          f"fade=t=in:st=0:d=0.5,fade=t=out:st={secs - 0.5}:d=0.5")
    out = V / f"part{i:02d}.mp4"
    run(["-f", "lavfi", "-i", f"color=c=0xfbfaf7:s={W}x{H}:d={secs}:r={FPS}", "-vf", vf,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
    return out


def scene(i, page, y0, y1, secs, cap):
    (V / f"c{i}.txt").write_text(cap, encoding="utf-8", newline="\n")
    capf = (V / f"c{i}.txt").as_posix().replace(":", "\\:")
    move = f"{y0}+({y1}-{y0})*min(max(t-1.5,0)/({secs}-3),1)"
    vf = (f"crop={W}:{H}:0:'{move}',"
          f"drawbox=x=0:y=ih-118:w=iw:h=118:color=0x1c1b19@0.88:t=fill,"
          f"drawtext=expansion=none:fontfile='{FONT}':textfile='{capf}':fontsize=28:fontcolor=white:line_spacing=10:"
          f"x=(w-text_w)/2:y=h-118+(118-text_h)/2,"
          f"fade=t=in:st=0:d=0.4,fade=t=out:st={secs - 0.4}:d=0.4")
    out = V / f"part{i:02d}.mp4"
    run(["-loop", "1", "-framerate", str(FPS), "-t", str(secs), "-i", str(V / f"{page}.png"), "-vf", vf,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), str(out)])
    return out


for _s in SCENES:
    capture(_s[0])
parts = [card(0, *CARD[0])]
for k, s in enumerate(SCENES, start=1):
    parts.append(scene(k, *s))
parts.append(card(len(SCENES) + 1, *END))
lst = V / "parts.txt"
lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8", newline="\n")   # relative to the list
run(["-f", "concat", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(OUT)])
print(OUT, sum(c[0] for c in CARD) + sum(s[3] for s in SCENES) + END[0], "s")
