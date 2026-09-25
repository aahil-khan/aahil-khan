#!/usr/bin/env python3
"""Render every SVG the profile README shows, in light and dark.

    pip install fonttools
    python3 scripts/render.py

The look follows aahil-khan.xyz: warm paper with a grid, Space Grotesk, a yellow
accent used sparingly, and neobrutalist cards (hard border, hard offset shadow).
Dark mode is the site's Tokyo Night theme.

An SVG shown through <img> cannot fetch anything, so fonts are subset to the
characters each file uses and embedded as data URIs. Embedding Space Mono also
means the ASCII art lines up the same in every browser.
"""

import base64
import html
import io
import pathlib
import re
import urllib.request
from collections import defaultdict

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT.parent / "assets"
FONT_DIR = ROOT / ".fonts"
LOGOS = ROOT / "logos"

FONT_URLS = {
    "SpaceGrotesk.ttf": "https://github.com/google/fonts/raw/main/ofl/spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf",
    "SpaceMono-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/spacemono/SpaceMono-Regular.ttf",
}

# Tokens from portfolio-canvas design/DIRECTION.md and content/themes.ts.
THEMES = {
    "light": dict(
        paper="#F7F5EE", glow="rgba(255,255,255,0.8)", grid="rgba(22,22,22,0.07)",
        surface="#FFFFFF", sunken="#F4F2EA", bar="#FDF7C4",
        ink="#161616", muted="rgba(22,22,22,0.62)", subtle="rgba(22,22,22,0.45)",
        accent="#FACC00", accent_ink="#161616", border="#161616",
    ),
    "dark": dict(
        paper="#1A1B26", glow="rgba(192,202,245,0.05)", grid="rgba(192,202,245,0.07)",
        surface="#16161E", sunken="#1F2335", bar="#24283B",
        ink="#C0CAF5", muted="#A9B1D6", subtle="#949EC8",
        accent="#E0AF68", accent_ink="#1A1B26", border="#C0CAF5",
    ),
}


# ----------------------------------------------------------------- fonts

def font_file(name):
    path = FONT_DIR / name
    if not path.exists():
        FONT_DIR.mkdir(exist_ok=True)
        urllib.request.urlretrieve(FONT_URLS[name], path)
    return path


_static = {}


def static_font(face):
    """Raw bytes of one face: ('G', weight) for Space Grotesk, ('M', 400) for Space Mono."""
    if face not in _static:
        family, weight = face
        if family == "G":
            font = instancer.instantiateVariableFont(TTFont(font_file("SpaceGrotesk.ttf")), {"wght": weight})
        else:
            font = TTFont(font_file("SpaceMono-Regular.ttf"))
        buf = io.BytesIO()
        font.save(buf)
        _static[face] = buf.getvalue()
    return _static[face]


_metrics = {}


def advance(face, s, size, spacing=0.0):
    """Width of s in px, from the font's own advance widths (kerning ignored)."""
    if face not in _metrics:
        font = TTFont(io.BytesIO(static_font(face)))
        _metrics[face] = (font.getBestCmap(), font["hmtx"], font["head"].unitsPerEm)
    cmap, hmtx, upm = _metrics[face]
    units = sum(hmtx[cmap.get(ord(ch), ".notdef")][0] for ch in s)
    return units / upm * size + spacing * size * len(s)


MONO = 0.612  # Space Mono's advance, in em


def font_face(face, chars):
    font = TTFont(io.BytesIO(static_font(face)))
    opts = subset.Options()
    opts.flavor = "woff"
    opts.layout_features = ["kern"]
    opts.name_IDs = []
    sub = subset.Subsetter(opts)
    sub.populate(text="".join(sorted(chars)))
    sub.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    data = base64.b64encode(buf.getvalue()).decode()
    family = "G" if face[0] == "G" else "M"
    return (f"@font-face{{font-family:{family};font-weight:{face[1]};"
            f"src:url(data:font/woff;base64,{data}) format('woff')}}")


# ------------------------------------------------------------ svg builder

def esc(s):
    return html.escape(s, quote=True)


class Svg:
    """One SVG file: collects elements, keyframes and the glyphs it uses."""

    def __init__(self, w, h, theme, title, still):
        self.w, self.h, self.t = w, h, THEMES[theme]
        self.title = title
        self.still = still  # the moment shown when motion is reduced
        self.parts, self.rules, self.defs = [], [], []
        self.used = defaultdict(set)

    def add(self, *parts):
        self.parts.extend(parts)

    def text(self, x, y, s, size=14, weight=400, mono=False, fill="ink", attrs="",
             spacing=None, anchor=None):
        face = ("M", 400) if mono else ("G", weight)
        self.used[face] |= set(s)
        fill = self.t.get(fill, fill)
        extra = ""
        if spacing:
            extra += f' letter-spacing="{spacing}em"'
        if anchor:
            extra += f' text-anchor="{anchor}"'
        return (f'<text x="{x:.2f}" y="{y:.2f}" font-family="{face[0]}" font-weight="{face[1]}" '
                f'font-size="{size}" fill="{fill}" xml:space="preserve"{extra} {attrs}>{esc(s)}</text>')

    def rich(self, x, y, runs, size=12, attrs=""):
        """One monospace line in several colours; runs are (text, colour-token)."""
        for s, _ in runs:
            self.used[("M", 400)] |= set(s)
        spans = "".join(f'<tspan fill="{self.t.get(c, c)}">{esc(s)}</tspan>' for s, c in runs)
        return (f'<text x="{x:.2f}" y="{y:.2f}" font-family="M" font-size="{size}" '
                f'xml:space="preserve" {attrs}>{spans}</text>')

    def win(self, spans, period, loop=False):
        """Attributes that show an element only during (start, end) spans, in seconds.

        step-end holds each keyframe until the next, so every switch is a hard cut.
        end=None keeps it on. Elements visible at self.still get class `fin`, which
        is what a reader who prefers reduced motion sees."""
        name = f"k{len(self.rules)}"
        frames = {0.0: 0}
        for start, end in spans:
            frames[round(start / period * 100, 3)] = 1
            if end is not None:
                frames[round(end / period * 100, 3)] = 0
        if 100.0 not in frames:
            frames[100.0] = frames[max(frames)]
        body = "".join(f"{p}%{{opacity:{v}}}" for p, v in sorted(frames.items()))
        self.rules.append(f"@keyframes {name}{{{body}}}")
        at = self.still % period if loop else self.still
        on = any(s <= at and (e is None or at < e) for s, e in spans)
        cls = ' class="fin"' if on else ""
        count = "infinite" if loop else "1"
        return f'{cls} style="opacity:0;animation:{name} {period}s step-end {count} forwards"'

    def rule(self, css):
        self.rules.append(css)

    def card(self, x, y, w, h, fill="surface", r=14, shadow=6):
        t = self.t
        return (f'<rect x="{x + shadow}" y="{y + shadow}" width="{w}" height="{h}" rx="{r}" fill="{t["border"]}"/>'
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{t.get(fill, fill)}" '
                f'stroke="{t["border"]}" stroke-width="2"/>')

    def window(self, x, y, w, h, title, bar=32):
        """A card with a title bar, like the windows on the site's canvas."""
        t = self.t
        r = 14
        path = (f"M{x} {y + bar}V{y + r}a{r} {r} 0 0 1 {r}-{r}h{w - 2 * r}"
                f"a{r} {r} 0 0 1 {r} {r}V{y + bar}z")
        dots = "".join(f'<circle cx="{x + 18 + i * 15}" cy="{y + bar / 2}" r="4.2" fill="none" '
                       f'stroke="{t["border"]}" stroke-width="1.6"/>' for i in range(3))
        return (self.card(x, y, w, h)
                + f'<path d="{path}" fill="{t["bar"]}" stroke="{t["border"]}" stroke-width="2"/>'
                + dots
                + self.text(x + 70, y + bar / 2 + 4.5, title, size=12.5, weight=500, fill="muted"))

    def paper(self, x, y, w, h, grid=40):
        """The site's floor: warm paper, a soft glow from the top and a faint grid."""
        t = self.t
        gid = f"g{len(self.defs)}"
        self.defs.append(
            f'<pattern id="{gid}p" width="{grid}" height="{grid}" patternUnits="userSpaceOnUse" '
            f'x="{x}" y="{y}"><path d="M{grid} 0V{grid}H0" fill="none" stroke="{t["grid"]}"/></pattern>'
            f'<radialGradient id="{gid}r" cx="0.5" cy="0" r="0.8"><stop offset="0" stop-color="{t["glow"]}"/>'
            f'<stop offset="1" stop-color="{t["glow"]}" stop-opacity="0"/></radialGradient>'
            f'<clipPath id="{gid}c"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14"/></clipPath>')
        return (self.card(x, y, w, h, fill="paper")
                + f'<g clip-path="url(#{gid}c)"><rect x="{x}" y="{y}" width="{w}" height="{h}" fill="url(#{gid}p)"/>'
                + f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="url(#{gid}r)"/></g>'
                + f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="none" stroke="{self.t["border"]}" stroke-width="2"/>')

    def render(self):
        faces = "\n".join(font_face(f, chars) for f, chars in sorted(self.used.items()) if chars)
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" role="img" aria-labelledby="t">
<title id="t">{esc(self.title)}</title>
<defs>{''.join(self.defs)}</defs>
<style>
{faces}
{chr(10).join(self.rules)}
@media (prefers-reduced-motion: reduce){{*{{animation:none!important}}.fin{{opacity:1!important}}}}
</style>
{chr(10).join(self.parts)}
</svg>
"""


# ------------------------------------------------------------ animation kit

def typed(c, x, y, s, t0, period, cps=16, end=None, size=12, fill="ink", loop=True):
    """Type s one character at a time from t0, keep it until end."""
    cw = MONO * size
    out = []
    for i, ch in enumerate(s):
        if ch == " ":
            continue
        out.append(c.text(x + i * cw, y, ch, size=size, mono=True, fill=fill,
                          attrs=c.win([(t0 + i / cps, end)], period, loop)))
    return "".join(out), t0 + len(s) / cps


def frames(c, x, y, variants, spans, period, size=12, fill="ink"):
    """Show variants[i] during spans[i]: a flip-book on one line."""
    return "".join(c.text(x, y, v, size=size, mono=True, fill=fill, attrs=c.win([sp], period, True))
                   for v, sp in zip(variants, spans))


# ------------------------------------------------------------------ hero

HERO_CAT = [
    "  /\\_/\\",
    " ( o.o )",
    " /  ^  \\",
    "(_)___(_)",
]
HERO_CAT_BLINK = " ( -.- )"
HERO_TAIL = (["", ")", "(", ")"], ["", "(", ")", "("])


def hero(theme):
    W, H = 840, 470
    c = Svg(W, H, theme, "Aahil Khan. Full-stack engineer building AI retrieval and agent systems that "
            "hold up in production. Bareilly, India. 9.16 CGPA, 3 hackathon wins, 3 domains, 2 internships. "
            "An ASCII cat sits on a window listing what he is doing now.", still=6)
    t = c.t
    c.add(c.paper(2, 2, W - 10, H - 10))

    x0 = 40
    c.add(c.text(x0, 58, "BAREILLY, INDIA", size=11, weight=500, fill="muted", spacing=0.16))
    lx = x0 + advance(("G", 500), "BAREILLY, INDIA", 11, 0.16) + 14
    c.add(f'<line x1="{lx:.1f}" y1="54" x2="480" y2="54" stroke="{t["subtle"]}" stroke-width="1"/>')

    # The name rises into place, like the site's hero.
    c.rule("@keyframes rise{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}")
    for i, (word, y) in enumerate([("AAHIL", 150), ("KHAN", 236)]):
        c.add(f'<g style="animation:rise .7s cubic-bezier(.16,1,.3,1) {0.1 + i * 0.12}s both">'
              + c.text(x0 - 4, y, word, size=100, weight=700, spacing=-0.03) + "</g>")

    # Headline: the bold phrase lands word by word, then gets its highlighter.
    c.add(c.text(x0, 292, "Full-stack engineer building", size=22))
    words = "AI retrieval and agent systems".split()
    wx = x0
    for i, word in enumerate(words):
        c.add(c.text(wx, 322, word, size=22, weight=700, attrs=c.win([(0.6 + i * 0.14, None)], 3)))
        wx += advance(("G", 700), word + " ", 22)
    c.add(c.text(x0, 352, "that hold up in production.", size=22))
    hl_w = advance(("G", 700), "AI retrieval and agent systems", 22)
    c.rule(f"@keyframes swipe{{from{{transform:scaleX(0)}}to{{transform:scaleX(1)}}}}")
    c.add(f'<rect x="{x0}" y="327" width="{hl_w:.1f}" height="5" rx="1.5" fill="{t["accent"]}" '
          f'style="transform-box:fill-box;transform-origin:left;animation:swipe .6s cubic-bezier(.16,1,.3,1) 1.5s both"/>')

    # Stats row, as on the site.
    c.add(f'<line x1="{x0}" y1="386" x2="{W - 48}" y2="386" stroke="{t["subtle"]}" stroke-width="1"/>')
    sx = x0
    for num, label in [("9.16", "CGPA"), ("3", "WINS"), ("3", "DOMAINS"), ("2", "INTERNSHIPS")]:
        c.add(c.text(sx, 424, num, size=28, weight=700))
        c.add(c.text(sx, 443, label, size=9.5, weight=500, fill="muted", spacing=0.16))
        sx += max(advance(("G", 700), num, 28), advance(("G", 500), label, 9.5, 0.16)) + 34

    # now.txt, with a cat sitting on it.
    wx0, wy0, ww, wh = 530, 124, 262, 222
    c.add(c.window(wx0, wy0, ww, wh, "now.txt"))
    fs, lh = 12, 19.5
    lines = [
        [("research", "accent_label"), ("  Samsung PRISM", "ink")],
        [("          accent-invariant", "muted")],
        [("          speech LLMs", "muted")],
        [("building", "accent_label"), ("  AI interviews", "ink")],
        [("          at Oddmind", "muted")],
        [("studying", "accent_label"), ("  Thapar, final yr", "ink")],
        [("          + IIT Madras", "muted")],
        [("          diploma", "muted")],
    ]
    label_colour = t["ink"] if theme == "light" else t["accent"]
    for i, runs in enumerate(lines):
        runs = [(s, label_colour if col == "accent_label" else col) for s, col in runs]
        c.add(c.rich(wx0 + 20, wy0 + 58 + i * lh, runs, size=fs,
                     attrs=c.win([(1.0 + i * 0.09, None)], 3)))

    # The cat: blinks, and swings its tail over the edge of the window,
    # clear of the window's shadow so it doesn't vanish into it.
    cs, clh = 17, 17
    cw = MONO * cs
    edge = wx0 + ww + 8
    cx = edge - 10.5 * cw
    base = wy0 - 5
    for i, row in enumerate(HERO_CAT):
        y = base - (len(HERO_CAT) - 1 - i) * clh
        if i == 1:
            c.add(c.text(cx, y, row, size=cs, mono=True, attrs=c.win([(0, 4.2), (4.35, 4.9), (5.05, None)], 6.5, True)))
            c.add(c.text(cx, y, HERO_CAT_BLINK, size=cs, mono=True, attrs=c.win([(4.2, 4.35), (4.9, 5.05)], 6.5, True)))
        else:
            c.add(c.text(cx, y, row, size=cs, mono=True))
    c.add(c.text(cx + 9 * cw, base, "_", size=cs, mono=True))
    swing = 1.6
    for j in range(1, 4):
        y = base + j * clh - 3
        c.add(c.text(edge, y, HERO_TAIL[0][j], size=cs, mono=True, attrs=c.win([(0, swing / 2)], swing, True)))
        c.add(c.text(edge, y, HERO_TAIL[1][j], size=cs, mono=True, attrs=c.win([(swing / 2, None)], swing, True)))
    # Now and then it has something to say.
    c.add(c.text(cx - 40, base - 2 * clh - 4, "mrrp", size=11, mono=True, fill="muted",
                 attrs=c.win([(2.2, 3.6)], 11, True)))
    return c.render()


# ------------------------------------------------------------- work cards

def card_shell(c, title, name, tagline, award, stack):
    W, H = c.w, c.h
    c.add(c.window(2, 2, W - 10, H - 10, title))
    t = c.t
    if award:
        aw = advance(("G", 700), award, 9.5, 0.08) + 20
        ax = W - 8 - 14 - aw
        c.add(f'<rect x="{ax:.1f}" y="9" width="{aw:.1f}" height="19" rx="9.5" fill="{t["accent"]}" '
              f'stroke="{t["border"]}" stroke-width="1.6"/>')
        c.add(c.text(ax + 10, 22.2, award, size=9.5, weight=700, fill="accent_ink", spacing=0.08))
    c.add(f'<rect x="18" y="48" width="{W - 46}" height="140" rx="8" fill="{t["sunken"]}"/>')
    c.add(c.text(20, 222, name, size=21, weight=700))
    c.add(c.text(20, 244, tagline, size=13, fill="muted"))
    c.add(c.text(20, 268, "  ·  ".join(stack), size=10, weight=500, fill="subtle", spacing=0.06))


def sop_opera(theme):
    c = Svg(420, 292, theme, "SOP Opera: agentic industrial safety intelligence. Winner, Economic Times "
            "AI Hackathon 2.0. A sensor trace crosses its limit, an agent acts, and the decision joins a "
            "tamper-evident hash chain.", still=5)
    card_shell(c, "sop-opera", "SOP Opera", "Agentic industrial safety intelligence",
               "WINNER · ET AI HACKATHON 2.0", ["PYTHON", "LANGGRAPH", "FASTAPI", "NEXT.JS"])
    t = c.t
    fs = 12
    cw = MONO * fs
    x0, y0, lh = 30, 74, 21
    col0, cols = 10, 36          # trace columns on screen
    unit = "_.-~-._.-~-.__.-~-._.-"  # one lap of the trace
    spike_at = len(unit)
    unit_full = unit + "/\\" + "_.-~-._"
    U = len(unit_full)
    step = 0.11
    period = U * step
    reps = cols // U + 3
    trace = unit_full * reps
    clip = f"sc{theme}"
    c.defs.append(f'<clipPath id="{clip}"><rect x="{x0 + col0 * cw}" y="{y0 - 14}" width="{cols * cw}" height="40"/></clipPath>')
    c.rule(f"@keyframes scroll{{to{{transform:translateX(-{U * cw:.2f}px)}}}}")
    runs = []
    for k in range(reps):
        runs += [(unit, "muted"), ("/\\", t["accent"] if theme == "dark" else "#E4572E"), ("_.-~-._", "muted")]
    c.add(c.text(x0, y0, "vibration", size=fs, mono=True, fill="subtle"))
    c.add(f'<g clip-path="url(#{clip})"><g style="animation:scroll {period:.2f}s steps({U}) infinite">'
          + c.rich(x0 + col0 * cw, y0, runs, size=fs) + "</g></g>")
    # The limit marker; the spike reaches it once a lap.
    m = col0 + 28
    c.add(f'<line x1="{x0 + m * cw + cw / 2:.1f}" y1="{y0 - 16}" x2="{x0 + m * cw + cw / 2:.1f}" y2="{y0 + 6}" '
          f'stroke="{t["subtle"]}" stroke-dasharray="2 3"/>')
    hit = ((col0 + spike_at - m) % U) * step
    alert = (hit, hit + 1.6)
    c.add(c.rich(x0, y0 + lh * 1.3, [("limit ", "subtle"), ("! over threshold", "ink")], size=fs,
                 attrs=c.win([alert], period, True)))
    # Each alert gets a decision, and the decision gets hashed onto the chain.
    laps = 4
    long = period * laps
    blocks = ["a3f9", "9c1e", "e07b", "41d2"]
    acts = ["isolate pump P-12", "notify shift lead", "lock valve V-3", "log and close"]
    for k in range(laps):
        t0 = hit + k * period + 0.3
        s, _ = typed(c, x0, y0 + lh * 2.6, "agent  " + acts[k], t0, long, cps=40,
                     end=min(t0 + period - 0.4, long), size=fs)
        c.add(s)
    chain_y = y0 + lh * 4.2
    c.add(c.text(x0, chain_y, "audit", size=fs, mono=True, fill="subtle"))
    for k, b in enumerate(blocks):
        at = hit + k * period + 0.9
        seg = f"[{b}]" if k == 0 else f"-[{b}]"
        cx = x0 + (7 + k * 7) * cw - (cw if k else 0)
        c.add(c.text(cx, chain_y, seg, size=fs, mono=True, attrs=c.win([(at, long - 0.2)], long, True)))
    return c.render()


def konta(theme):
    c = Svg(420, 292, theme, "Konta: local-first, context-aware browsing. Winner, Samsung PRISM Web Agent "
            "Hackathon. Open tabs become a knowledge graph you can search in plain words.", still=6.5)
    card_shell(c, "konta", "Konta", "Local-first context-aware browsing",
               "WINNER · SAMSUNG PRISM", ["REACT", "TYPESCRIPT", "CHROME"])
    fs = 12
    cw = MONO * fs
    x0, y0, lh = 30, 72, 16
    P = 9.0
    end = P - 0.5
    tabs = [(0, "[github]"), (10, "[arxiv]"), (19, "[docs]"), (27, "[youtube]")]
    for k, (col, tab) in enumerate(tabs):
        c.add(c.text(x0 + col * cw, y0, tab, size=fs, mono=True, fill="muted", attrs=c.win([(0.2 + k * 0.35, end)], P, True)))
    graph = [
        "   \\         |        |        /",
        "    o--------o--------o-------o",
        "         \\       /  \\     /",
        "          o-----o    o---o",
    ]
    for i, g in enumerate(graph):
        c.add(c.text(x0, y0 + (i + 1) * lh, g, size=fs, mono=True, fill="subtle",
                     attrs=c.win([(1.8 + i * 0.25, end)], P, True)))
    q, done = typed(c, x0, y0 + 5.3 * lh, '? "that rag paper from tuesday"', 3.2, P, cps=18, end=end, size=fs)
    c.add(q)
    c.add(c.rich(x0, y0 + 6.3 * lh, [("  -> ", "subtle"), ("arxiv.org/abs/2312.10997", "ink")], size=fs,
                 attrs=c.win([(done + 0.3, end)], P, True)))
    # The tab, edge and node it came from light up.
    hi = "#E4572E" if theme == "light" else c.t["accent"]
    lit = c.win([(done + 0.3, end)], P, True)
    for col, row, glyph in [(10, 0, "[arxiv]"), (13, 1, "|"), (13, 2, "@")]:
        y = y0 + row * lh
        c.add(f'<g {lit}><rect x="{x0 + col * cw:.1f}" y="{y - 11}" width="{len(glyph) * cw:.1f}" height="14" '
              f'fill="{c.t["sunken"]}"/>' + c.text(x0 + col * cw, y, glyph, size=fs, mono=True, fill=hi) + "</g>")
    return c.render()


def flowsync(theme):
    c = Svg(420, 292, theme, "FlowSync AI: project memory for coding agents, over MCP. Innovation Award, "
            "Agentic AI Hackathon, Ulster University. Git pushes stream into a project brain that an agent "
            "can question later.", still=7)
    card_shell(c, "flowsync", "FlowSync AI", "Project memory for coding agents, over MCP",
               "INNOVATION AWARD · ULSTER", ["TYPESCRIPT", "PYTHON", "AWS", "BEDROCK"])
    t = c.t
    fs = 12
    cw = MONO * fs
    x0, y0, lh = 30, 72, 17
    P = 10.0
    end = P - 0.5
    s, t1 = typed(c, x0, y0, "$ git push origin main", 0.2, P, cps=20, end=end, size=fs)
    c.add(s)
    commits = [("3f2a", "switch vector store to qdrant"), ("9b1c", "cache embeddings per repo")]
    for k, (h, msg) in enumerate(commits):
        c.add(c.rich(x0, y0 + (k + 1) * lh, [(f"  {h} ", "subtle"), (msg, "ink")], size=fs,
                     attrs=c.win([(t1 + 0.3 + k * 0.3, end)], P, True)))
    # Packets travel into the brain; its memory fills.
    py = y0 + 3.3 * lh
    c.add(c.text(x0, py, "  ----------> [ project brain ]", size=fs, mono=True, fill="subtle",
                 attrs=c.win([(t1 + 0.9, end)], P, True)))
    t2 = t1 + 1.1
    for k in range(3):
        for j in range(11):
            at = t2 + k * 0.55 + j * 0.045
            c.add(c.text(x0 + (2 + j) * cw, py, "*", size=fs, mono=True, fill="ink",
                         attrs=c.win([(at, at + 0.045)], P, True)))
    fill = ["[##--------]", "[#####-----]", "[########--]"]
    spans = [(t2 + 0.5, t2 + 1.05), (t2 + 1.05, t2 + 1.6), (t2 + 1.6, end)]
    c.add(frames(c, x0 + 32 * cw, py, fill, spans, P, size=fs, fill="muted"))
    q, t3 = typed(c, x0, y0 + 4.8 * lh, "agent> why did we move to qdrant?", t2 + 2.0, P, cps=22, end=end, size=fs)
    c.add(q)
    c.add(c.rich(x0, y0 + 5.9 * lh, [("brain> ", "subtle"), ("see 3f2a, ", "ink"), ('"switch vector store"', "muted")],
                 size=fs, attrs=c.win([(t3 + 0.4, end)], P, True)))
    return c.render()


def gina(theme):
    c = Svg(420, 292, theme, "GINA: natural language to SQL analytics. A question becomes a query, and "
            "the query becomes a chart.", still=7.5)
    card_shell(c, "gina", "GINA", "Natural language → SQL analytics", None,
               ["NEXT.JS", "TYPESCRIPT", "POSTGRESQL"])
    fs = 12
    cw = MONO * fs
    x0, y0, lh = 30, 72, 16
    P = 10.0
    end = P - 0.5
    q, t1 = typed(c, x0, y0, "> top 3 cities by revenue", 0.2, P, cps=16, end=end, size=fs)
    c.add(q)
    sql = [
        [("SELECT ", "subtle"), ("city, SUM(revenue) AS rev", "ink")],
        [("FROM ", "subtle"), ("sales ", "ink"), ("GROUP BY ", "subtle"), ("city", "ink")],
        [("ORDER BY ", "subtle"), ("rev ", "ink"), ("DESC LIMIT ", "subtle"), ("3", "ink")],
    ]
    for i, runs in enumerate(sql):
        c.add(c.rich(x0, y0 + (i + 1) * lh, runs, size=fs, attrs=c.win([(t1 + 0.4 + i * 0.25, end)], P, True)))
    t2 = t1 + 1.6
    bars = [("Delhi ", 16, "4.2M"), ("Mumbai", 12, "3.1M"), ("Pune  ", 7, "1.8M")]
    for i, (city, n, val) in enumerate(bars):
        y = y0 + (i + 4.4) * lh
        c.add(c.text(x0, y, city, size=fs, mono=True, fill="muted", attrs=c.win([(t2, end)], P, True)))
        # Each bar grows a block at a time.
        for j in range(n):
            at = t2 + 0.2 + i * 0.15 + j * 0.05
            c.add(c.text(x0 + (8 + j) * cw, y, "#", size=fs, mono=True, fill="ink",
                         attrs=c.win([(at, end)], P, True)))
        c.add(c.text(x0 + (9 + n) * cw, y, val, size=fs, mono=True, fill="subtle",
                     attrs=c.win([(t2 + 0.2 + i * 0.15 + n * 0.05, end)], P, True)))
    return c.render()


# ------------------------------------------------------------------ stack

STACK = [
    ("Languages", [("Python", "python-original"), ("TypeScript", "Typescript"), ("JavaScript", "javascript-original")]),
    ("Frameworks", [("React", "react-original"), ("Next.js", "nextjs-original"), ("Node.js", "nodejs-original"),
                    ("Express", "express-original"), ("FastAPI", "FastAPI"), ("Flask", "flask-original")]),
    ("Databases", [("PostgreSQL", "postgresql-original"), ("MySQL", "mysql-original"), ("Redis", "redis-original"),
                   ("DynamoDB", "dynamodb-original"), ("Prisma", "prisma-original")]),
    ("Cloud & DevOps", [("AWS", "amazonwebservices-original-wordmark"), ("Docker", "docker-original"),
                        ("GitHub Actions", "githubactions-original"), ("Nginx", "nginx"), ("Git", "git-original")]),
    ("AI / ML", [("RAG", None), ("LangGraph", None), ("Vector search", None), ("LLMs", None), ("Multi-agent systems", None)]),
    ("Testing", [("Jest", "jest-plain"), ("Vitest", "Vitest")]),
]
# Marks too dark to read on the dark theme; there they are drawn in the ink colour.
DARK_MARKS = {"express-original", "amazonwebservices-original-wordmark", "prisma-original",
              "flask-original", "mysql-original"}

# Felix Lee's sleeping cat, a classic of the form.
NAP = [
    "      |\\      _,,,---,,_",
    "      /,`.-'`'    -.  ;-;;,_",
    "     |,4-  ) )-,_. ,\\ (  `'-'",
    "    '---''(_/--'  `-'\\_)",
]


def logo_uri(name):
    data = (LOGOS / f"{name}.svg").read_bytes()
    return "data:image/svg+xml;base64," + base64.b64encode(data).decode()


def stack(theme):
    W = 840
    row_h, top = 48, 118
    H = top + len(STACK) * row_h + 44
    names = ", ".join(n for _, tools in STACK for n, _ in tools)
    c = Svg(W, H, theme, f"What I build with: {names}. A cat is asleep on the last row.", still=5)
    t = c.t
    c.add(c.paper(2, 2, W - 10, H - 10))
    c.add(c.text(40, 54, "TOOLBOX", size=11, weight=500, fill="muted", spacing=0.16))
    c.add(c.text(40, 88, "What I build with", size=28, weight=700, spacing=-0.01))
    if theme == "dark":
        r, g, b = (int(t["ink"][i:i + 2], 16) / 255 for i in (1, 3, 5))
        c.defs.append(f'<filter id="inv"><feColorMatrix type="matrix" '
                      f'values="0 0 0 0 {r:.3f} 0 0 0 0 {g:.3f} 0 0 0 0 {b:.3f} 0 0 0 1 0"/></filter>')
    c.rule("@keyframes pop{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}")
    n = 0
    for r, (label, tools) in enumerate(STACK):
        y = top + r * row_h
        c.add(c.text(40, y + 19, label.upper(), size=10.5, weight=500, fill="muted", spacing=0.12))
        x = 196
        for name, logo in tools:
            tw = advance(("G", 500), name, 13)
            w = tw + (48 if logo else 26)
            parts = [f'<rect x="{x + 3}" y="{y + 3}" width="{w:.1f}" height="30" rx="8" fill="{t["border"]}"/>',
                     f'<rect x="{x}" y="{y}" width="{w:.1f}" height="30" rx="8" fill="{t["surface"]}" '
                     f'stroke="{t["border"]}" stroke-width="1.8"/>']
            tx = x + 13
            if logo:
                filt = ' filter="url(#inv)"' if theme == "dark" and logo in DARK_MARKS else ""
                parts.append(f'<image x="{x + 11}" y="{y + 7}" width="16" height="16" href="{logo_uri(logo)}"{filt}/>')
                tx = x + 35
            parts.append(c.text(tx, y + 19.5, name, size=13, weight=500))
            c.add(f'<g style="animation:pop .45s cubic-bezier(.16,1,.3,1) {0.15 + n * 0.035:.3f}s both">'
                  + "".join(parts) + "</g>")
            n += 1
            x += w + 12
    # A cat asleep at the end of the testing row.
    fs = 13
    nx = W - 52 - MONO * fs * 29
    ny = top + (len(STACK) - 1) * row_h + 14
    for i, row in enumerate(NAP):
        c.add(c.text(nx, ny + i * 15, row, size=fs, mono=True, fill="muted"))
    c.rule("@keyframes zz{0%{opacity:0;transform:translate(0,0)}25%{opacity:1}100%{opacity:0;transform:translate(10px,-26px)}}")
    for j, size in enumerate([10, 12, 14]):
        c.add(f'<g style="opacity:0;animation:zz 3.6s linear {j * 1.2}s infinite">'
              + c.text(nx + 2 + j * 9, ny + 12, "z", size=size, mono=True, fill="subtle") + "</g>")
    return c.render()


# ----------------------------------------------------------------- footer

WALK_HEAD = "      /\\_/\\"
WALK_EYES = (" ____/ o o \\", " ____/ - - \\")
WALK_TAIL = ("/~____  =^= /", "\\~____  =^= /")
WALK_PAWS = ("(______)__m_m)", "(_m____)_m__m)")


def footer(theme):
    W, H = 840, 250
    c = Svg(W, H, theme, "Let's build something. Open for cool builds and interesting problems. "
            "A cat strolls along the bottom, stops to say mrrp, and walks off.", still=8.5)
    t = c.t
    c.add(c.paper(2, 2, W - 10, H - 10))
    c.add(c.text(40, 54, "CONTACT", size=11, weight=500, fill="muted", spacing=0.16))
    c.add(c.text(40, 96, "Let's build something.", size=34, weight=700, spacing=-0.02))
    c.add(c.text(40, 124, "Open for cool builds and interesting problems. Email is fastest, I answer all of them.",
                 size=14, fill="muted"))

    period = 18.0
    fs, lh = 14, 16.5
    cw = MONO * fs
    base = 164
    x0, xs, x1 = -130, W / 2 - 60, W + 20
    stop, go = 0.45, 0.58

    def alternate(t0, t1, dt):
        spans, s = [], t0
        while s < t1:
            spans.append((s, min(s + dt, t1)))
            s += 2 * dt
        return spans

    def swap(row, pair, spans_b):
        spans_a, cur = [], 0.0
        for s, e in sorted(spans_b):
            if s > cur:
                spans_a.append((cur, s))
            cur = e
        if cur < period:
            spans_a.append((cur, period))
        y = base + row * lh
        return (c.text(0, y, pair[0], size=fs, mono=True, attrs=c.win(spans_a, period, True))
                + c.text(0, y, pair[1], size=fs, mono=True, attrs=c.win(spans_b, period, True)))

    walking = [(0, stop * period), (go * period, period)]
    paws = [sp for w in walking for sp in alternate(w[0] + 0.3, w[1], 0.3)]
    tail = [sp for w in walking for sp in alternate(w[0] + 0.6, w[1], 0.6)]
    pause = stop * period
    blink = [(pause + 0.5, pause + 0.65), (pause + 1.4, pause + 1.55), (3.1, 3.25), (13.4, 13.55)]
    cat = (c.text(0, base, WALK_HEAD, size=fs, mono=True)
           + swap(1, WALK_EYES, blink) + swap(2, WALK_TAIL, tail) + swap(3, WALK_PAWS, paws)
           + c.text(12 * cw, base - 18, "mrrp?", size=11, mono=True, fill="muted",
                    attrs=c.win([(pause + 0.4, go * period - 0.3)], period, True)))
    clip = f"fc{theme}"
    c.defs.append(f'<clipPath id="{clip}"><rect x="4" y="100" width="{W - 14}" height="{H - 110}" rx="12"/></clipPath>')
    c.rule(f"@keyframes cross{{0%{{transform:translateX({x0}px)}}{stop * 100:.1f}%,{go * 100:.1f}%"
           f"{{transform:translateX({xs}px)}}100%{{transform:translateX({x1}px)}}}}")
    ground = base + 3 * lh + 9
    c.add(f'<line x1="40" y1="{ground}" x2="{W - 48}" y2="{ground}" stroke="{t["subtle"]}" '
          f'stroke-width="1.5" stroke-dasharray="2 7" stroke-linecap="round"/>')
    c.rule(f"@media (prefers-reduced-motion: reduce){{.walker{{transform:translateX({xs}px)}}}}")
    c.add(f'<g clip-path="url(#{clip})"><g class="walker" style="animation:cross {period}s linear infinite">{cat}</g></g>')
    return c.render()


PIECES = {
    "hero": hero, "work-sop-opera": sop_opera, "work-konta": konta, "work-flowsync": flowsync,
    "work-gina": gina, "stack": stack, "footer": footer,
}


def main():
    OUT.mkdir(exist_ok=True)
    for name, fn in PIECES.items():
        for theme in THEMES:
            svg = fn(theme)
            (OUT / f"{name}-{theme}.svg").write_text(svg)
    sizes = {p.name: p.stat().st_size // 1024 for p in sorted(OUT.glob("*.svg"))}
    print("  ".join(f"{k} {v}K" for k, v in sizes.items()))


if __name__ == "__main__":
    main()
