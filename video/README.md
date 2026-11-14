# Launch video

A 50-second, 1920x1080 launch video rendered with [Remotion](https://www.remotion.dev). Every number on screen
comes from one export (`data/make_data.py`), the site shots come from the site build, and the soundtrack is
synthesised by `music/make_track.py` (no samples, no third-party audio). Cuts sit on the bar lines of the
120 BPM track: `src/kit.tsx` holds the grid (`BEAT` = 15 frames, `BAR` = 60).

From the repository root:

```sh
uv run python video/data/make_data.py                        # src/data.json from the newest export
uv run --with numpy --with scipy python video/music/make_track.py   # public/track.wav
uv run python -c "import sys; sys.path.insert(0,'src'); from pathlib import Path; from callrec import site; \
  site.build_site(sorted(Path('data/exports').iterdir())[-1], Path('site/build'))"
# serve site/ (python -m http.server 8765 in site/), then capture dark full-page shots with a Chromium browser:
#   index.html at 1920x5600 -> video/public/site-full.png
cp site/static/fonts/*.woff2 video/public/
cd video && npm i
npx remotion render Launch out/launch-raw.mp4 --codec=h264 --crf=16
ffmpeg -i out/launch-raw.mp4 -c:v copy -af "loudnorm=I=-14:TP=-1.5:LRA=9" -c:a aac -b:a 192k \
  -movflags +faststart out/reopen-ledger-launch.mp4
```

`npx remotion studio` opens the timeline for edits. Remotion's own licence applies to Remotion itself (free for
individuals and small teams; see remotion.dev/license).
