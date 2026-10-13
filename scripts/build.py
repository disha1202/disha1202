#!/usr/bin/env python3
"""Render profile.json into an animated terminal SVG (profile/terminal.svg) and README.md.

Usage:  python scripts/build.py            # uses GITHUB_TOKEN if set, for live stats
        python scripts/build.py --offline  # never call the GitHub API
"""
import hashlib
import json
import os
import re
import sys
import urllib.request
from html import escape
from pathlib import Path

import pyfiglet

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "profile.json").read_text())
OFFLINE = "--offline" in sys.argv or CFG["username"].startswith("YOUR_")

W = 980            # canvas width
X0 = 60            # left text margin
CW = 9.0           # monospace char width at 15px
LH = 20            # line height
GAP = 14           # space between command blocks


# ───────────────────────── GitHub data ─────────────────────────

def gh(path):
    req = urllib.request.Request("https://api.github.com" + path,
                                 headers={"Accept": "application/vnd.github+json"})
    if tok := os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def fetch_stats(user):
    repos = gh(f"/users/{user}/repos?per_page=100&type=owner")
    own = [r for r in repos if not r["fork"]]
    langs = {}
    for r in own:
        for lang, n in gh(f"/repos/{user}/{r['name']}/languages").items():
            langs[lang] = langs.get(lang, 0) + n
    prs = gh(f"/search/issues?q=author:{user}+type:pr&per_page=1")["total_count"]
    issues = gh(f"/search/issues?q=author:{user}+type:issue&per_page=1")["total_count"]
    stars = sum(r["stargazers_count"] for r in own)
    return {"langs": langs, "summary": f"{prs} PRs, {issues} issues, {len(own)} repos, {stars}★"}


stats = None
if not OFFLINE:
    try:
        stats = fetch_stats(CFG["username"])
    except Exception as e:  # keep building with fallbacks if the API is unavailable
        print(f"warning: GitHub API failed ({e}); using fallbacks", file=sys.stderr)


# ───────────────────────── SVG building ─────────────────────────

out = []          # svg elements
y = 78            # current baseline
t = 0.04          # current animation time (s)


def esc(s):
    return escape(str(s), quote=True)


def fade(inner, dur=0.18, step=0.05):
    global t
    out.append(f'<g class="fade" style="animation:fade {dur}s ease {t:.2f}s forwards">{inner}</g>')
    t += step


def line(spans, x=X0, size=None, step=0.05):
    """spans: list of (class, text). Emits one faded-in line and advances y."""
    global y
    fs = f' font-size="{size}"' if size else ""
    body = "".join(f'<tspan class="{c}">{esc(s)}</tspan>' for c, s in spans)
    fade(f'<text x="{x}" y="{y}" xml:space="preserve"{fs}>{body}</text>', step=step)
    y += LH


def prompt(cmd):
    """A prompt line whose command is 'typed' left to right."""
    global y, t
    y += GAP
    host = CFG["host"]
    p = f'<tspan class="pr">{esc(host)}</tspan><tspan class="mu">:~</tspan><tspan class="br"> (main)</tspan><tspan class="mu">$ </tspan>'
    fade(f'<text x="{X0}" y="{y}" xml:space="preserve">{p}</text>', dur=0.1, step=0.12)
    px = X0 + (len(host) + 11) * CW
    dur = max(0.25, len(cmd) * 0.035)
    out.append(
        f'<g class="type" style="animation:type {dur:.2f}s steps({len(cmd) + 1},end) {t:.2f}s forwards">'
        f'<text x="{px}" y="{y}" class="cm" xml:space="preserve">{esc(cmd)}</text></g>')
    t += dur + 0.15
    y += LH + 4


def frame(height):
    return (f'<rect x="20" y="16" width="{W-40}" height="{height-32}" rx="12" fill="#0d1117" stroke="#30363d"/>'
            f'<path d="M20 28 A12 12 0 0 1 32 16 H{W-32} A12 12 0 0 1 {W-20} 28 V56 H20 Z" fill="#161b22"/>'
            f'<line x1="20" y1="56" x2="{W-20}" y2="56" stroke="#30363d"/>'
            '<circle cx="42" cy="36" r="6" fill="#ff5f57"/><circle cx="62" cy="36" r="6" fill="#febc2e"/>'
            '<circle cx="82" cy="36" r="6" fill="#28c840"/>'
            f'<text x="{W/2}" y="41" text-anchor="middle" class="di" font-size="13">{esc(CFG["host"])} · session</text>')


# boot log
for msg in CFG["boot"]:
    line([("di", "[  "), ("ok", "OK"), ("di", "  ] "), ("mu", msg)], size=14)

# figlet banner, drawn as shapes so it looks identical regardless of the viewer's fonts:
# █ → solid cell, box-drawing shadow chars → thin strokes
STROKES = {"═": "lr", "║": "ud", "╗": "ld", "╔": "rd", "╝": "lu", "╚": "ru"}


def figlet(text):
    return [l for l in pyfiglet.figlet_format(text, font="ansi_shadow").splitlines() if l.strip()]


y += 14
max_w = W - 140
words, rows, cur = CFG["banner"].split(), [], ""
for w_ in words:  # wrap words onto extra rows at the 11px-equivalent cell size
    trial = f"{cur} {w_}".strip()
    if cur and max(map(len, figlet(trial))) * 6.6 > max_w:
        rows.append(cur)
        cur = w_
    else:
        cur = trial
rows.append(cur)
cell_w = max(6.6, min(9, max_w / max(max(map(len, figlet(r))) for r in rows)))
cell_h = cell_w * 1.9
for row in rows:
    art = figlet(row)
    ax = (W - max(map(len, art)) * cell_w) / 2
    for a in art:
        shapes = []
        for m in re.finditer("█+", a):  # one rect per horizontal run avoids hairline seams
            shapes.append(f'<rect x="{ax + m.start() * cell_w:.1f}" y="{y:.1f}" '
                          f'width="{(m.end() - m.start()) * cell_w:.1f}" height="{cell_h + .5:.1f}"/>')
        for i, ch in enumerate(a):
            cx, cy = ax + i * cell_w, y
            if ch in STROKES:
                mx, my = cx + cell_w / 2, cy + cell_h / 2
                ends = {"l": (cx, my), "r": (cx + cell_w, my), "u": (mx, cy), "d": (mx, cy + cell_h)}
                d = "".join(f"M{mx:.1f} {my:.1f}L{ends[k][0]:.1f} {ends[k][1]:.1f}" for k in STROKES[ch])
                shapes.append(f'<path d="{d}" class="sh"/>')
        fade(f'<g fill="url(#wm)">{"".join(shapes)}</g>', dur=0.3, step=0.04)
        y += cell_h
    y += 12
y += 10
fade(f'<text x="{W/2}" y="{y}" text-anchor="middle" class="di" font-size="14">{esc(CFG["subtitle"])}</text>')
y += 16

# neofetch: generated binary "orb" logo + info column
prompt("neofetch")
seed = hashlib.sha256(CFG["username"].encode()).digest()
R, logo = 13, []
for r in range(-R, R + 1):
    row = ""
    for c in range(-2 * R, 2 * R + 1):
        inside = (c / 2) ** 2 + r ** 2 <= R * R
        # diagonal bands of 1s/0s, phase-shifted per username
        row += ("1" if (c + 2 * r + seed[0]) // 3 % 2 else "0") if inside else " "
    if len(row.strip()) > 6:  # drop the stubby single-char poles
        logo.append(row.rstrip())
logo_y = y
for i, l in enumerate(logo):
    out.append(f'<g class="fade" style="animation:fade .2s ease {t + i*0.02:.2f}s forwards">'
               f'<text x="{X0}" y="{logo_y + i*12}" xml:space="preserve" class="logo" fill="url(#lg)">{esc(l)}</text></g>')
info_x = X0 + 4 * R * 6.2 + 50
y = logo_y + 30
host = CFG["host"]
line([("pr", host)], x=info_x)
line([("di", "-" * len(host))], x=info_x)
for k, v in CFG["neofetch"]:
    if v == "auto":
        v = stats["summary"] if stats else "see cards below"
    line([("na", f"{k}: "), ("tx", v)], x=info_x)
y += 8
swatches = ["#484f58", "#ff7b72", "#9ece6a", "#febc2e", "#56d4dd", "#d2a8ff", "#7ee3c7", "#e6edf3"]
fade("".join(f'<rect x="{info_x + i*26}" y="{y-14}" width="24" height="16" fill="{c}"/>' for i, c in enumerate(swatches)))
y = max(y + LH, logo_y + len(logo) * 12) + 6

# remaining sections
for sec in CFG["sections"]:
    prompt(sec["cmd"])
    kind = sec["type"]
    if kind == "table":
        cols = [h for h in sec["headers"]]
        widths = [max(len(str(r[i])) for r in [cols] + sec["rows"]) + 3 for i in range(len(cols))]
        xs = [X0 + sum(widths[:i]) * CW for i in range(len(cols))]
        def row(cells, classes):
            global y
            fade("".join(f'<text x="{xs[i]:.0f}" y="{y}" class="{classes[i]}">{esc(c)}</text>'
                         for i, c in enumerate(cells)))
            y += LH
        row(cols, ["di"] * len(cols))
        for r in sec["rows"]:
            row(r, ["na", "tx", "di" if r[2].startswith("Exited") else "ok", "ac"])
    elif kind == "bullets":
        pad = max(len(a) for a, _ in sec["items"]) + 2
        for a, b in sec["items"]:
            line([("ac", "• "), ("cm", a.ljust(pad)), ("di", "→  "), ("tx", b)])
    elif kind == "kv":
        pad = max(len(a) for a, _ in sec["items"]) + 3
        for a, b in sec["items"]:
            line([("na", a.ljust(pad)), ("tx", b)])
    elif kind == "languages":
        if sec.get("auto") and stats and stats["langs"]:
            total = sum(stats["langs"].values())
            items = sorted(((k, v * 100 / total) for k, v in stats["langs"].items()), key=lambda kv: -kv[1])
        else:
            total = sum(v for _, v in sec["fallback"])
            items = [(k, v * 100 / total) for k, v in sec["fallback"]]
        items = items[: sec.get("top", 6)]
        lab = max(len(k) for k, _ in items) + 2
        bx, bw = X0 + lab * CW, 300
        for k, pct in items:
            fade(f'<text x="{X0}" y="{y}" class="cm">{esc(k)}</text>'
                 f'<rect x="{bx}" y="{y-11}" width="{bw}" height="12" rx="2" fill="#21262d"/>'
                 f'<rect x="{bx}" y="{y-11}" width="{max(2, bw*pct/100):.1f}" height="12" rx="2" fill="url(#bar)"/>'
                 f'<text x="{bx + bw + 14}" y="{y}" class="mu">{pct:.1f}%</text>')
            y += LH
    elif kind == "text":
        line([(sec.get("class", "ok"), sec["text"])])

# final prompt with blinking cursor
y += GAP
fade(f'<text x="{X0}" y="{y}" xml:space="preserve"><tspan class="pr">{esc(host)}</tspan><tspan class="mu">:~</tspan>'
     f'<tspan class="br"> (main)</tspan><tspan class="mu">$ </tspan></text>'
     f'<rect class="cur" x="{X0 + (len(host)+11)*CW}" y="{y-13}" width="9" height="16" fill="#9ece6a"/>')
H = int(y + 40)

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="ui-monospace, 'SF Mono', SFMono-Regular, 'JetBrains Mono', Menlo, Consolas, monospace" role="img" aria-label="{esc(CFG['banner'])}">
  <defs>
    <linearGradient id="wm" gradientUnits="userSpaceOnUse" x1="140" y1="0" x2="840" y2="0">
      <stop offset="0" stop-color="#9ece6a"/><stop offset="0.55" stop-color="#7ee3c7"/><stop offset="1" stop-color="#56d4dd"/>
    </linearGradient>
    <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#9ece6a"/><stop offset="1" stop-color="#56d4dd"/>
    </linearGradient>
    <linearGradient id="bar" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#9ece6a"/><stop offset="1" stop-color="#56d4dd"/>
    </linearGradient>
  </defs>
  <style>
    text {{ font-size: 15px; }}
    .sh {{ fill: none; stroke: #56d4dd; stroke-opacity: .45; stroke-width: 1.4; stroke-linecap: square; }}
    .logo {{ font-size: 10px; }}
    .fade {{ opacity: 0; }}
    .type {{ clip-path: inset(0 100% 0 0); }}
    .cur {{ animation: blink 1s steps(1) infinite; }}
    @keyframes type {{ to {{ clip-path: inset(-6px -12% -6px 0); }} }}
    @keyframes fade {{ to {{ opacity: 1; }} }}
    @keyframes blink {{ 50% {{ opacity: 0; }} }}
    @media (prefers-reduced-motion: reduce) {{
      .fade {{ opacity:1!important; animation:none!important; }}
      .type {{ clip-path:none!important; animation:none!important; }}
      .cur {{ animation:none!important; }}
    }}
    .pr{{fill:#9ece6a}} .cm{{fill:#e6edf3}} .mu{{fill:#8b949e}} .di{{fill:#6e7681}}
    .na{{fill:#56d4dd}} .tx{{fill:#c9d1d9}} .ok{{fill:#3fb950}} .ac{{fill:#9ece6a}} .br{{fill:#d2a8ff}}
  </style>
  {frame(H)}
  {chr(10).join(out)}
</svg>
'''
(ROOT / "profile" / "terminal.svg").write_text(svg)

# ───────────────────────── README ─────────────────────────

u = CFG["username"]
badges = "\n".join(
    f'  <a href="{esc(url)}"><img src="https://img.shields.io/badge/{label.replace("-", "--").replace(" ", "_")}-0d1117'
    f'?style=for-the-badge&logo={logo}&logoColor={color}"></a>'
    for label, logo, url, color in CFG["links"])
readme = f'''<p align="center">
  <img src="./profile/terminal.svg" alt="{esc(CFG['banner'])} — terminal" width="980" />
</p>

<p align="center">
{badges}
</p>

<p align="center">
  <img src="./profile/stats.svg" height="170" />
  <img src="./profile/top-langs.svg" height="170" />
</p>

<p align="center">
  <img src="https://streak-stats.demolab.com?user={u}&background=0d1117&border=30363d&stroke=30363d&ring=56d4dd&fire=56d4dd&currStreakNum=e6edf3&sideNums=e6edf3&currStreakLabel=56d4dd&sideLabels=adbac7&dates=6e7681" />
</p>
'''
(ROOT / "README.md").write_text(readme)
print(f"wrote profile/terminal.svg ({W}x{H}) and README.md")
