#!/usr/bin/env python3
"""Render the profile README's animated SVGs.

  assets/catfetch-{dark,light}.svg  a neofetch-style terminal with a live cat
  assets/walk-{dark,light}.svg      a cat that strolls along the footer

Stats come from the GitHub API when GH_TOKEN is set; otherwise the script
falls back to placeholders so it still renders locally. Standard library only,
so the workflow needs no install step.
"""

import datetime as dt
import html
import json
import os
import pathlib
import urllib.request

USER = "aahil-khan"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
OUT = pathlib.Path(__file__).resolve().parent.parent / "assets"

# Catppuccin, the cat-flavoured palette: Mocha for dark mode, Latte for light.
THEMES = {
    "dark": dict(
        bg="#1e1e2e", bar="#181825", edge="#313244", text="#cdd6f4", dim="#6c7086",
        cat="#f9e2af", key="#cba6f7", prompt="#a6e3a1", accent="#f5c2e7", blue="#89b4fa",
        swatch=["#f38ba8", "#fab387", "#f9e2af", "#a6e3a1", "#94e2d5", "#89b4fa", "#cba6f7", "#f5c2e7"],
    ),
    "light": dict(
        bg="#eff1f5", bar="#e6e9ef", edge="#ccd0da", text="#4c4f69", dim="#9ca0b0",
        cat="#df8e1d", key="#8839ef", prompt="#40a02b", accent="#ea76cb", blue="#1e66f5",
        swatch=["#d20f39", "#fe640b", "#df8e1d", "#40a02b", "#179299", "#1e66f5", "#8839ef", "#ea76cb"],
    ),
}

FONT = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', 'DejaVu Sans Mono', monospace"


# --------------------------------------------------------------------- stats

def gql(query, token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": USER},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    if "errors" in body:
        raise RuntimeError(body["errors"])
    return body["data"]


def fetch_stats(now):
    token = os.environ.get("GH_TOKEN")
    if not token:
        return dict(created=dt.datetime(2023, 10, 14, tzinfo=dt.timezone.utc),
                    repos=52, total=2237, streak=41, recent=True)
    data = gql(f"""{{ user(login: "{USER}") {{
        createdAt
        repositories(ownerAffiliations: OWNER, privacy: PUBLIC) {{ totalCount }}
        contributionsCollection {{ contributionCalendar {{
            totalContributions
            weeks {{ contributionDays {{ date contributionCount }} }}
        }} }}
    }} }}""", token)["user"]
    cal = data["contributionsCollection"]["contributionCalendar"]
    days = [d for w in cal["weeks"] for d in w["contributionDays"]]
    days = [d for d in days if d["date"] <= now.date().isoformat()]
    counts = [d["contributionCount"] for d in days]
    # A streak survives until the end of today, so an empty today doesn't break it.
    if counts and counts[-1] == 0:
        counts = counts[:-1]
    streak = 0
    for c in reversed(counts):
        if not c:
            break
        streak += 1
    recent = any(d["contributionCount"] for d in days[-2:])
    return dict(
        created=dt.datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00")),
        repos=data["repositories"]["totalCount"],
        total=cal["totalContributions"],
        streak=streak,
        recent=recent,
    )


def uptime(created, now):
    months = (now.year - created.year) * 12 + now.month - created.month
    if now.day < created.day:
        months -= 1
    y, m = divmod(months, 12)
    return f"{y}y {m}m" if y else f"{m}m"


# ------------------------------------------------------------- svg helpers

def esc(s):
    return html.escape(s, quote=False)


class Anim:
    """Collects one @keyframes rule per element that needs its own timeline."""

    def __init__(self):
        self.rules = []

    def windows(self, spans, period, loop=False):
        """Visible only during the given (start, end) spans, in seconds.

        step-end holds each keyframe until the next, so every switch is a hard
        cut, like a terminal repainting a line. end=None means stay visible."""
        name = f"k{len(self.rules)}"
        frames = {0.0: 0}
        for start, end in spans:
            frames[start / period * 100] = 1
            if end is not None:
                frames[end / period * 100] = 0
        if 100.0 not in frames:
            frames[100.0] = frames[max(frames)]
        body = " ".join(f"{p:.3f}%{{opacity:{v}}}" for p, v in sorted(frames.items()))
        self.rules.append(f"@keyframes {name}{{{body}}}")
        count = "infinite" if loop else "1"
        return (f'style="opacity:0;animation:{name} {period}s step-end {count} forwards"')

    def raw(self, rule):
        self.rules.append(rule)

    def css(self):
        return "\n".join(self.rules)


def text(x, y, s, fill, extra=""):
    return (f'<text x="{x}" y="{y}" fill="{fill}" xml:space="preserve" {extra}>'
            f"{esc(s)}</text>")


# ------------------------------------------------------------------- the cat

CAT = [
    "    /\\_____/\\",
    "   /  o   o  \\",
    "  ( ==  ^  == )",
    "   )         (",
    "  (           )",
    " ( (  )   (  ) )",
    "(__(__)___(__)__)",
]
EYES_SHUT = "   /  -   -  \\"
# Tail overlays: padded with spaces so each glyph lands in its own column,
# whatever the font's advance width turns out to be.
TAIL_REST = {4: "                  (", 5: "                   )", 6: "                 _/"}
TAIL_FLICK = {4: "                    )", 5: "                   /", 6: "                 _/"}


def catfetch(theme, stats, now):
    t = THEMES[theme]
    a = Anim()
    fs, lh, cw = 14, 21, 8.4          # font size, line height, nominal advance
    pad, top = 28, 58
    width = 840
    info_x = pad + 25 * cw

    awake = stats["recent"]
    stamp = now.strftime("%d %b, %H:%M IST").lstrip("0")
    info = [
        ("Location", "Bareilly, India"),
        ("Study", "Computer Engineering, Thapar (final year)"),
        ("", "+ Diploma in Programming, IIT Madras"),
        ("Research", "Samsung PRISM: accent-invariant SpeechLLMs"),
        ("Building", "an AI interview platform at Oddmind"),
        ("Langs", "Python, TypeScript"),
        ("Into", "RAG, LangGraph, vector search, agents"),
        ("Trophies", "3 hackathon awards, 2 of them first place"),
        ("Commits", f"{stats['total']:,} in the last year"),
        ("Streak", f"{stats['streak']} day{'s' if stats['streak'] != 1 else ''}"),
        ("Repos", f"{stats['repos']} public"),
        ("Uptime", f"{uptime(stats['created'], now)} on GitHub"),
        ("Cat", f"awake, fed {stamp}" if awake else f"asleep since the last push ({stamp})"),
    ]

    body = []
    prompt = "aahil@github ~ $ "
    cmd = "catfetch"
    type_start, step = 0.6, 0.09
    out_start = type_start + len(cmd) * step + 0.35
    line_step = 0.045

    def row(i):
        return top + i * lh

    # Prompt, then the command typed one key at a time.
    body.append(text(pad, row(0), "aahil@github", t["prompt"]))
    body.append(text(pad, row(0), " " * 12 + " ~ $", t["blue"]))
    for i, ch in enumerate(cmd):
        body.append(text(pad, row(0), " " * (len(prompt) + i) + ch, t["text"],
                         a.windows([(type_start + i * step, None)], out_start + 1)))
    for i in range(len(cmd) + 1):
        start = 0 if i == 0 else type_start + (i - 1) * step + step
        end = out_start if i == len(cmd) else type_start + i * step + step
        if i == 0:
            end = type_start + step
        body.append(text(pad, row(0), " " * (len(prompt) + i) + "\u2588", t["dim"],
                         a.windows([(start, end)], out_start + 1)))

    # Output: each line lands a beat after the last, like a real print.
    def reveal(i):
        return a.windows([(out_start + i * line_step, None)], out_start + 2)

    first = 2
    for i, line in enumerate(CAT):
        y = row(first + i)
        if i == 1:
            if awake:
                blink = 5.0
                body.append(f'<g {reveal(i)}>'
                            + text(pad, y, line, t["cat"], a.windows([(0, 4.6), (4.75, None)], blink, loop=True))
                            + text(pad, y, EYES_SHUT, t["cat"], a.windows([(4.6, 4.75)], blink, loop=True))
                            + "</g>")
            else:
                body.append(text(pad, y, EYES_SHUT, t["cat"], reveal(i)))
            continue
        body.append(text(pad, y, line, t["cat"], reveal(i)))
        if i in TAIL_REST:
            if awake:
                flick = 3.6
                body.append(f'<g {reveal(i)}>'
                            + text(pad, y, TAIL_REST[i], t["cat"],
                                   a.windows([(0, 2.4), (2.7, 2.9), (3.2, None)], flick, loop=True))
                            + text(pad, y, TAIL_FLICK[i], t["cat"],
                                   a.windows([(2.4, 2.7), (2.9, 3.2)], flick, loop=True))
                            + "</g>")
            else:
                body.append(text(pad, y, TAIL_REST[i], t["cat"], reveal(i)))

    if not awake:
        a.raw("@keyframes zz{0%{opacity:0;transform:translate(0,0)}20%{opacity:1}"
              "100%{opacity:0;transform:translate(14px,-34px)}}")
        for j, (dx, size) in enumerate([(0, 11), (10, 13), (20, 15)]):
            body.append(f'<text x="{pad + 16 * cw + dx}" y="{row(first)}" fill="{t["dim"]}" '
                        f'font-size="{size}" style="opacity:0;animation:zz 3s linear {j}s infinite">z</text>')

    # Info column, neofetch style.
    body.append(text(info_x, row(first), "aahil", t["key"], reveal(0)))
    body.append(text(info_x, row(first), "     @github", t["text"], reveal(0)))
    body.append(text(info_x, row(first + 1), "\u2500" * 12, t["dim"], reveal(1)))
    for i, (k, v) in enumerate(info):
        y = row(first + 2 + i)
        body.append(f'<g {reveal(2 + i)}>'
                    + text(info_x, y, k, t["key"])
                    + text(info_x, y, " " * 10 + v, t["text"])
                    + "</g>")

    # The colour strip neofetch always ends on.
    strip_y = row(first + 2 + len(info)) + 10
    sw = 22
    for i, c in enumerate(t["swatch"]):
        body.append(f'<rect x="{info_x + i * (sw + 6)}" y="{strip_y}" width="{sw}" height="12" rx="3" '
                    f'fill="{c}" {reveal(len(info) + 3)}/>')

    # Fresh prompt with a blinking cursor once everything has printed.
    last = first + 2 + len(info) + 2
    done = out_start + (len(info) + 4) * line_step
    body.append(f'<g {a.windows([(done, None)], done + 1)}>'
                + text(pad, row(last), "aahil@github", t["prompt"])
                + text(pad, row(last), " " * 12 + " ~ $", t["blue"])
                + text(pad, row(last), " " * len(prompt) + "\u2588", t["dim"],
                       a.windows([(0, 0.55)], 1.1, loop=True))
                + "</g>")

    height = row(last) + 26
    dots = "".join(f'<circle cx="{24 + i * 18}" cy="18" r="5.5" fill="{c}"/>'
                   for i, c in enumerate(t["swatch"][i] for i in (0, 2, 3)))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="t">
<title id="t">catfetch: Aahil Khan. Computer Engineering at Thapar, research at Samsung PRISM, full-stack AI at Oddmind. {stats['total']:,} contributions in the last year. The cat is {'awake' if awake else 'asleep'}.</title>
<style>
text{{font-family:{FONT};font-size:{fs}px}}
{a.css()}
@media (prefers-reduced-motion: reduce){{*{{animation-duration:0s!important;animation-delay:0s!important;animation-iteration-count:1!important}}}}
</style>
<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12" fill="{t['bg']}" stroke="{t['edge']}"/>
<path d="M0.5 36V12.5a12 12 0 0 1 12-12h{width - 25}a12 12 0 0 1 12 12V36z" fill="{t['bar']}"/>
<line x1="0.5" y1="36" x2="{width - 0.5}" y2="36" stroke="{t['edge']}"/>
{dots}
<text x="{width / 2}" y="22.5" fill="{t['dim']}" text-anchor="middle" style="font-size:12px">aahil@github: ~</text>
{chr(10).join(body)}
</svg>
"""


# ------------------------------------------------------------ footer walker

# The loaf cat, in frames: blink, tail swish, and a two-step paw shuffle.
WALK_HEAD = "      /\\_/\\"
WALK_EYES = (" ____/ o o \\", " ____/ - - \\")
WALK_TAIL = ("/~____  =^= /", "\\~____  =^= /")
WALK_PAWS = ("(______)__m_m)", "(_m____)_m__m)")


def walk(theme):
    t = THEMES[theme]
    a = Anim()
    width, height, fs, lh = 840, 110, 16, 19
    base = 30
    period = 18.0
    # Stroll in, stop in the middle to say something, stroll off.
    x0, xs, x1 = -170, width / 2 - 70, width + 20
    stop, go = 0.45, 0.58

    def between(t0, t1, dt):
        """Alternating (on, off) spans for one frame of a looping cycle."""
        spans, s = [], t0
        while s < t1:
            spans.append((s, min(s + dt, t1)))
            s += 2 * dt
        return spans

    walking = [(0, stop * period), (go * period, period)]
    step = 0.3
    paws_b = [sp for w in walking for sp in between(w[0] + step, w[1], step)]
    tail_b = [sp for w in walking for sp in between(w[0] + 0.6, w[1], 0.6)]
    blink = [(stop * period + 0.5, stop * period + 0.65), (stop * period + 1.4, stop * period + 1.55)]
    blink += [(s, s + 0.15) for s in (3.1, 13.4)]

    def frame(row, s, spans=None):
        style = a.windows(spans, period, loop=True) if spans is not None else ""
        return text(0, base + row * lh, s, t["cat"], style)

    def swap(row, pair, spans_b):
        # No background to paint over, so A shows exactly when B doesn't.
        spans_a, cur = [], 0.0
        for s, e in sorted(spans_b):
            if s > cur:
                spans_a.append((cur, s))
            cur = e
        if cur < period:
            spans_a.append((cur, period))
        return frame(row, pair[0], spans_a) + frame(row, pair[1], spans_b)

    cat = (frame(0, WALK_HEAD)
           + swap(1, WALK_EYES, blink)
           + swap(2, WALK_TAIL, tail_b)
           + swap(3, WALK_PAWS, paws_b))
    say_at = stop * period + 0.4
    speech = text(118, base - 6, "mrrp?", t["dim"], a.windows([(say_at, go * period - 0.3)], period, loop=True) + ' class="say"')
    a.raw(f"@keyframes cross{{0%{{transform:translateX({x0}px)}}"
          f"{stop * 100:.1f}%,{go * 100:.1f}%{{transform:translateX({xs}px)}}"
          f"100%{{transform:translateX({x1}px)}}}}")
    ground = base + 3 * lh + 8
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="t">
<title id="t">An ASCII cat strolls along the bottom of the page, stops to say mrrp, and walks off</title>
<style>
text{{font-family:{FONT};font-size:{fs}px}}
.say{{font-size:12px}}
{a.css()}
.walker{{animation:cross {period}s linear infinite}}
@media (prefers-reduced-motion: reduce){{.walker{{animation:none;transform:translateX({xs}px)}}}}
</style>
<line x1="0" y1="{ground}" x2="{width}" y2="{ground}" stroke="{t['edge']}" stroke-width="1.5" stroke-dasharray="2 7" stroke-linecap="round"/>
<g class="walker">{cat}{speech}</g>
</svg>
"""


def main():
    now = dt.datetime.now(IST)
    stats = fetch_stats(now)
    OUT.mkdir(exist_ok=True)
    for theme in THEMES:
        (OUT / f"catfetch-{theme}.svg").write_text(catfetch(theme, stats, now))
        (OUT / f"walk-{theme}.svg").write_text(walk(theme))
    print(f"rendered: {stats['total']} contributions, streak {stats['streak']}, "
          f"cat {'awake' if stats['recent'] else 'asleep'}")


if __name__ == "__main__":
    main()
