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
        # The site's recessed band: 9% ink mixed into the paper.
        band="#E3E1DB", signal="#E4572E", page="#FFFFFF",
    ),
    "dark": dict(
        paper="#1A1B26", glow="rgba(192,202,245,0.05)", grid="rgba(192,202,245,0.07)",
        surface="#16161E", sunken="#1F2335", bar="#24283B",
        ink="#C0CAF5", muted="#A9B1D6", subtle="#949EC8",
        accent="#E0AF68", accent_ink="#1A1B26", border="#C0CAF5",
        band="#292B39", signal="#E0AF68", page="#0D1117",
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

# The classic cat, sitting on now.txt with its paws over the edge.
HERO_HEAD = "  /\\_/\\"
HERO_EYES = {"open": " ( o.o )", "blink": " ( -.- )", "happy": " ( ^.^ )"}
HERO_BODY = ["  > ^ <", ' (")_(")']


NOW = [
    ("building", "AI interviews"),
    ("", "at Oddmind"),
    ("tinkering", "GNOME extensions"),
    ("chasing", "OSS contributions"),
    ("studying", "Thapar, final yr"),
    ("", "+ IIT Madras"),
    ("", "diploma"),
]


def hero(theme):
    W, H = 840, 404
    c = Svg(W, H, theme, "Aahil Khan, Bareilly, India. Full-stack engineer building AI retrieval and agent "
            "systems that hold up in production. A cat sits on a now.txt window: building AI interviews "
            "at Oddmind, tinkering with GNOME extensions, chasing OSS contributions, final year at Thapar "
            "plus an IIT Madras diploma.", still=6)
    t = c.t
    c.add(c.paper(2, 2, W - 10, H - 10))

    x0 = 40
    c.add(c.text(x0, 58, "BAREILLY, INDIA", size=11, weight=500, fill="muted", spacing=0.16))
    lx = x0 + advance(("G", 500), "BAREILLY, INDIA", 11, 0.16) + 14
    c.add(f'<line x1="{lx:.1f}" y1="54" x2="460" y2="54" stroke="{t["subtle"]}" stroke-width="1"/>')

    # The name rises into place, like the site's hero.
    c.rule("@keyframes rise{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}")
    for i, (word, y) in enumerate([("AAHIL", 150), ("KHAN", 236)]):
        c.add(f'<g style="animation:rise .7s cubic-bezier(.16,1,.3,1) {0.1 + i * 0.12}s both">'
              + c.text(x0 - 4, y, word, size=100, weight=700, spacing=-0.03) + "</g>")

    # Headline: the bold phrase lands word by word, then gets its highlighter.
    c.add(c.text(x0, 294, "Full-stack engineer building", size=22))
    wx = x0
    for i, word in enumerate("AI retrieval and agent systems".split()):
        c.add(c.text(wx, 324, word, size=22, weight=700, attrs=c.win([(0.6 + i * 0.14, None)], 3)))
        wx += advance(("G", 700), word + " ", 22)
    c.add(c.text(x0, 354, "that hold up in production.", size=22))
    hl_w = advance(("G", 700), "AI retrieval and agent systems", 22)
    c.rule("@keyframes swipe{from{transform:scaleX(0)}to{transform:scaleX(1)}}")
    c.add(f'<rect x="{x0}" y="329" width="{hl_w:.1f}" height="5" rx="1.5" fill="{t["accent"]}" '
          f'style="transform-box:fill-box;transform-origin:left;animation:swipe .6s cubic-bezier(.16,1,.3,1) 1.5s both"/>')

    # now.txt
    wx0, wy0, ww, wh = 496, 128, 272, 214
    c.add(c.window(wx0, wy0, ww, wh, "now.txt"))
    fs, lh = 12, 19.5
    label_colour = t["ink"] if theme == "light" else t["accent"]
    for i, (label, value) in enumerate(NOW):
        c.add(c.rich(wx0 + 20, wy0 + 58 + i * lh, [(f"{label:<11}", label_colour), (value, "ink" if label else "muted")],
                     size=fs, attrs=c.win([(1.0 + i * 0.09, None)], 3)))

    # The cat: a slow blink now and then, a contented squint, and a tail
    # resting on the ledge that sways a little.
    cs, clh = 15, 16
    cw = MONO * cs
    cx = wx0 + ww - 11 * cw
    base = wy0 - 4
    rows = [HERO_HEAD, None] + HERO_BODY
    period = 8.0
    eyes = {
        "open": [(0, 2.5), (2.9, 5.2), (6.6, None)],
        "blink": [(2.5, 2.9)],
        "happy": [(5.2, 6.6)],
    }
    for i, row in enumerate(rows):
        y = base - (len(rows) - 1 - i) * clh
        if row is None:
            for k, v in HERO_EYES.items():
                c.add(c.text(cx, y, v, size=cs, mono=True, attrs=c.win(eyes[k], period, True)))
        else:
            c.add(c.text(cx, y, row, size=cs, mono=True))
    tx, ty = cx + 8 * cw, base
    c.rule("@keyframes sway{from{transform:rotate(-7deg)}to{transform:rotate(7deg)}}")
    c.add(f'<g style="transform-origin:{tx:.1f}px {ty - 3}px;animation:sway 2.4s ease-in-out infinite alternate">'
          + c.text(tx, ty, "_/", size=cs, mono=True) + "</g>")
    return c.render()


# ----------------------------------------------------------------- buttons

def button(theme, kind, label):
    """One of the site's buttons, as its own image so each can be a link."""
    t = THEMES[theme]
    size = 15
    tw = advance(("G", 500), label, size)
    pad = 22
    if kind == "primary":
        w = pad + tw + 12 + 30 + 8
    else:
        w = pad + tw + pad
    W, H = int(w + 10), 56
    c = Svg(W, H, theme, label, still=2)
    h = 44
    c.add(f'<rect x="6" y="8" width="{w - 4:.1f}" height="{h}" rx="22" fill="{t["border"]}"/>'
          f'<rect x="2" y="4" width="{w - 4:.1f}" height="{h}" rx="22" fill="{t["surface"]}" '
          f'stroke="{t["border"]}" stroke-width="2"/>')
    c.add(c.text(pad, 4 + h / 2 + 5, label, size=size, weight=500))
    if kind == "primary":
        ax = pad + tw + 12 + 15
        c.rule("@keyframes go{0%,70%,100%{transform:translateX(0)}82%{transform:translateX(3px)}}")
        c.add(f'<circle cx="{ax:.1f}" cy="{4 + h / 2}" r="15" fill="{t["accent"]}" stroke="{t["border"]}" stroke-width="1.5"/>'
              f'<g style="animation:go 2.4s ease-in-out infinite">'
              + c.text(ax, 4 + h / 2 + 5.5, "→", size=16, weight=700, fill="accent_ink", anchor="middle") + "</g>")
    return c.render()


BUTTONS = {
    "site": ("primary", "Portfolio"),
    "resume": ("plain", "Résumé PDF ↓"),
    "linkedin": ("plain", "LinkedIn ↗"),
    "email": ("plain", "Email ↗"),
}


# ------------------------------------------------------------------- work

def work_head(theme):
    c = Svg(840, 96, theme, "Selected work: four things worth opening", still=1)
    c.add(c.text(4, 30, "SELECTED WORK", size=11, weight=500, fill="muted", spacing=0.16))
    c.add(c.text(4, 70, "Four things worth opening", size=30, weight=700, spacing=-0.015))
    c.add(f'<line x1="4" y1="94" x2="836" y2="94" stroke="{c.t["border"]}" stroke-width="2"/>')
    return c.render()


def work_row(c, num, name, tagline, award, stack):
    """An index entry: outlined number, name and award, blurb, stack, and an arrow.

    The right-hand third is left for the entry's ticker."""
    t = c.t
    c.add(c.text(4, 76, num, size=54, weight=700, fill="none", attrs=f'stroke="{t["ink"]}" stroke-width="1.3"'))
    c.add(c.text(104, 48, name, size=27, weight=700, spacing=-0.01))
    if award:
        ax = 104 + advance(("G", 700), name, 27, -0.01) + 14
        aw = advance(("G", 700), award, 9.5, 0.08) + 20
        c.add(f'<rect x="{ax:.1f}" y="30" width="{aw:.1f}" height="20" rx="10" fill="{t["accent"]}" '
              f'stroke="{t["border"]}" stroke-width="1.5"/>')
        c.add(c.text(ax + 10, 43.6, award, size=9.5, weight=700, fill="accent_ink", spacing=0.08))
    c.add(c.text(104, 74, tagline, size=14, fill="muted"))
    c.add(c.text(104, 100, "  ·  ".join(stack), size=10, weight=500, fill="subtle", spacing=0.08))
    c.rule("@keyframes out{0%,72%,100%{transform:translate(0,0)}84%{transform:translate(3px,-3px)}}")
    c.add(f'<g style="animation:out 3s ease-in-out infinite">'
          + c.text(832, 48, "↗", size=22, weight=500, anchor="end") + "</g>")
    c.add(f'<line x1="4" y1="{c.h - 1.5}" x2="836" y2="{c.h - 1.5}" stroke="{t["subtle"]}" stroke-width="1" '
          f'stroke-opacity="0.6"/>')


TX, FS = 540, 12      # where tickers start, and their size
CW = MONO * FS
ROW_Y = (40, 62, 84)


def sop_opera(theme):
    c = Svg(840, 124, theme, "02 SOP Opera: agentic industrial safety intelligence. Winner, Economic Times "
            "AI Hackathon 2.0. A sensor trace crosses its limit, an agent acts, and the decision joins a "
            "tamper-evident hash chain.", still=5)
    work_row(c, "02", "SOP Opera", "Agentic industrial safety intelligence", "WINNER · ET AI HACKATHON 2.0",
             ["PYTHON", "LANGGRAPH", "FASTAPI", "NEXT.JS"])
    t = c.t
    col0, cols = 4, 30
    unit = "_.-~-._.-~-.__.-~-._.-" + "/\\" + "_.-~-._"
    spike_at = unit.index("/\\")
    U = len(unit)
    step = 0.11
    period = U * step
    reps = cols // U + 3
    clip = f"sc{theme}"
    c.defs.append(f'<clipPath id="{clip}"><rect x="{TX + col0 * CW}" y="{ROW_Y[0] - 14}" width="{cols * CW}" height="20"/></clipPath>')
    c.rule(f"@keyframes scroll{{to{{transform:translateX(-{U * CW:.2f}px)}}}}")
    runs = []
    for _ in range(reps):
        runs += [(unit[:spike_at], "muted"), ("/\\", t["signal"]), (unit[spike_at + 2:], "muted")]
    c.add(c.text(TX, ROW_Y[0], "vib", size=FS, mono=True, fill="subtle"))
    c.add(f'<g clip-path="url(#{clip})"><g style="animation:scroll {period:.2f}s steps({U}) infinite">'
          + c.rich(TX + col0 * CW, ROW_Y[0], runs, size=FS) + "</g></g>")
    m = col0 + 24
    c.add(f'<line x1="{TX + m * CW + CW / 2:.1f}" y1="{ROW_Y[0] - 14}" x2="{TX + m * CW + CW / 2:.1f}" y2="{ROW_Y[0] + 5}" '
          f'stroke="{t["subtle"]}" stroke-dasharray="2 3"/>')
    hit = ((col0 + spike_at - m) % U) * step
    laps = 4
    long = period * laps
    acts = ["isolate pump P-12", "notify shift lead", "lock valve V-3", "log and close"]
    blocks = ["a3f9", "9c1e", "e07b", "41d2"]
    for k in range(laps):
        at = hit + k * period
        c.add(c.rich(TX, ROW_Y[1], [("! ", t["signal"]), (acts[k], "ink")], size=FS,
                     attrs=c.win([(at, min(at + period - 0.2, long))], long, True)))
        seg = f"[{blocks[k]}]" if k == 0 else f"-[{blocks[k]}]"
        bx = TX + (4 + k * 7 - (1 if k else 0)) * CW
        c.add(c.text(bx, ROW_Y[2], seg, size=FS, mono=True, attrs=c.win([(at + 0.6, long - 0.2)], long, True)))
    c.add(c.text(TX, ROW_Y[2], "log", size=FS, mono=True, fill="subtle"))
    return c.render()


def konta(theme):
    c = Svg(840, 124, theme, "03 Konta: local-first, context-aware browsing. Winner, Samsung PRISM Web Agent "
            "Hackathon. Open tabs become a graph you can search in plain words.", still=6.5)
    work_row(c, "03", "Konta", "Local-first context-aware browsing", "WINNER · SAMSUNG PRISM",
             ["REACT", "TYPESCRIPT", "CHROME"])
    P, end = 9.0, 8.5
    tabs = [(0, "[github]"), (9, "[arxiv]"), (17, "[docs]"), (24, "[yt]")]
    for k, (col, tab) in enumerate(tabs):
        c.add(c.text(TX + col * CW, ROW_Y[0], tab, size=FS, mono=True, fill="muted",
                     attrs=c.win([(0.2 + k * 0.3, end)], P, True)))
    nodes = [col + len(tab) // 2 for col, tab in tabs]
    graph = [" "] * (nodes[-1] + 1)
    for a, b in zip(nodes, nodes[1:]):
        for i in range(a, b):
            graph[i] = "-"
    for n in nodes:
        graph[n] = "o"
    c.add(c.text(TX, ROW_Y[1], "".join(graph), size=FS, mono=True, fill="subtle", attrs=c.win([(1.5, end)], P, True)))
    q, done = typed(c, TX, ROW_Y[2], '? "that rag paper"', 2.3, P, cps=16, end=end, size=FS)
    c.add(q)
    lit = c.win([(done + 0.3, end)], P, True)
    c.add(c.rich(TX + 18 * CW, ROW_Y[2], [(" -> ", "subtle"), ("arxiv", "ink")], size=FS, attrs=lit))
    # The tab and node it came from light up, covering the plain ones.
    for col, row, glyph in [(tabs[1][0], 0, tabs[1][1]), (nodes[1], 1, "@")]:
        y = ROW_Y[row]
        c.add(f'<g {lit}><rect x="{TX + col * CW:.1f}" y="{y - 11}" width="{len(glyph) * CW:.1f}" height="14" '
              f'fill="{c.t["page"]}"/>' + c.text(TX + col * CW, y, glyph, size=FS, mono=True, fill="signal") + "</g>")
    return c.render()


def flowsync(theme):
    c = Svg(840, 124, theme, "04 FlowSync AI: project memory for coding agents, over MCP. Innovation Award, "
            "Agentic AI Hackathon, Ulster University. Pushes stream into a project brain an agent can ask later.",
            still=7)
    work_row(c, "04", "FlowSync AI", "Project memory for coding agents, over MCP", "INNOVATION AWARD · ULSTER",
             ["TYPESCRIPT", "PYTHON", "AWS", "BEDROCK"])
    P, end = 10.0, 9.5
    s, t1 = typed(c, TX, ROW_Y[0], "$ git push origin main", 0.2, P, cps=20, end=end, size=FS)
    c.add(s)
    c.add(c.text(TX, ROW_Y[1], "  --------> [brain", size=FS, mono=True, fill="subtle", attrs=c.win([(t1 + 0.2, end)], P, True)))
    t2 = t1 + 0.4
    for k in range(3):
        for j in range(8):
            at = t2 + k * 0.5 + j * 0.05
            c.add(c.text(TX + (2 + j) * CW, ROW_Y[1], "*", size=FS, mono=True, attrs=c.win([(at, at + 0.05)], P, True)))
    fills = ["       ]", " #     ]", " ###   ]", " ##### ]"]
    spans = [(t1 + 0.2, t2 + 0.4), (t2 + 0.4, t2 + 0.9), (t2 + 0.9, t2 + 1.4), (t2 + 1.4, end)]
    c.add(frames(c, TX + 18 * CW, ROW_Y[1], fills, spans, P, size=FS, fill="muted"))
    q, t3 = typed(c, TX, ROW_Y[2], "? why qdrant", t2 + 1.9, P, cps=16, end=end, size=FS)
    c.add(q)
    c.add(c.rich(TX + 12 * CW, ROW_Y[2], [(" -> ", "subtle"), ("see 3f2a", "ink")], size=FS,
                 attrs=c.win([(t3 + 0.3, end)], P, True)))
    return c.render()


def holt(theme):
    c = Svg(840, 124, theme, "01 holt: finds open-source projects that will actually merge your first PR. "
            "Winner, micro1 Frontier Engineering Challenge. It reads a repository's pull-request history "
            "and returns a verdict.", still=7)
    work_row(c, "01", "holt", "Finds OSS projects that will actually merge your first PR",
             "WINNER · MICRO1 FRONTIER ENGINEERING CHALLENGE", ["PYTHON", "TYPESCRIPT", "GITHUB API"])
    P, end = 10.0, 9.5
    s, t1 = typed(c, TX, ROW_Y[0], "$ holt analyze owner/repo", 0.2, P, cps=18, end=end, size=FS)
    c.add(s)
    c.add(c.text(TX, ROW_Y[1], "reading PRs", size=FS, mono=True, fill="subtle", attrs=c.win([(t1 + 0.2, end)], P, True)))
    bars = ["[      ]", "[##    ]", "[####  ]", "[######]"]
    spans = [(t1 + 0.2 + k * 0.5, t1 + 0.7 + k * 0.5 if k < 3 else end) for k in range(4)]
    c.add(frames(c, TX + 12 * CW, ROW_Y[1], bars, spans, P, size=FS, fill="muted"))
    t2 = t1 + 2.4
    c.add(c.rich(TX, ROW_Y[2], [("verdict ", "subtle"), ("Worth your time", c.t["signal"])], size=FS,
                 attrs=c.win([(t2, end)], P, True)))
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

# A small cat trotting left: two strides that shift its paws one column.
TROT_HEAD = " /\\_/\\"
TROT_BODY = ("( o.o )___/", "( -.- )___/")
TROT_PAWS = (' " "  " "', '  " "  " "')


def footer(theme):
    W, H = 840, 222
    c = Svg(W, H, theme, "Let's build something. Open for cool builds and interesting problems; email is "
            "fastest. A small cat trots across, stops to blink, and trots on.", still=8)
    t = c.t
    c.add(c.card(2, 2, W - 10, H - 10, fill="band"))
    c.add(c.text(40, 54, "CONTACT", size=11, weight=500, fill="muted", spacing=0.16))
    c.add(c.text(40, 96, "Let’s build something.", size=34, weight=700, spacing=-0.02))
    c.add(c.text(40, 124, "Open for cool builds and interesting problems. Email is fastest, I answer all of them.",
                 size=14, fill="muted"))

    fs, lh = 13, 14
    top = 156
    period = 20.0
    stride = 0.2
    x_in, x_stop, x_out = W + 10, W / 2 - 40, -110
    speed = 55.0                                   # px per second, steady
    t_stop = (x_in - x_stop) / speed
    t_go = t_stop + 2.2
    t_gone = t_go + (x_stop - x_out) / speed

    def alternate(t0, t1, phase):
        return [(s, min(s + stride, t1)) for k, s in enumerate(frange(t0, t1, stride)) if k % 2 == phase]

    moving = [(0, t_stop), (t_go, period)]
    paws_b = [sp for a, b in moving for sp in alternate(a, b, 1)]
    paws_a = [sp for a, b in moving for sp in alternate(a, b, 0)] + [(t_stop, t_go)]
    blink = [(t_stop + 0.8, t_stop + 1.0)]
    open_eyes = [(0, blink[0][0]), (blink[0][1], None)]
    cat = (c.text(0, top, TROT_HEAD, size=fs, mono=True)
           + c.text(0, top + lh, TROT_BODY[0], size=fs, mono=True, attrs=c.win(open_eyes, period, True))
           + c.text(0, top + lh, TROT_BODY[1], size=fs, mono=True, attrs=c.win(blink, period, True))
           + c.text(0, top + 2 * lh, TROT_PAWS[0], size=fs, mono=True, attrs=c.win(paws_a, period, True))
           + c.text(0, top + 2 * lh, TROT_PAWS[1], size=fs, mono=True, attrs=c.win(paws_b, period, True)))
    # A slight bob while trotting, still while stopped.
    c.rule("@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-1px)}}")
    pct = lambda s: f"{s / period * 100:.2f}%"
    c.rule("@keyframes trot{"
           f"0%{{transform:translateX({x_in:.1f}px)}}"
           f"{pct(t_stop)},{pct(t_go)}{{transform:translateX({x_stop:.1f}px)}}"
           f"{pct(t_gone)},100%{{transform:translateX({x_out:.1f}px)}}}}")
    c.rule(f"@media (prefers-reduced-motion: reduce){{.cat{{transform:translateX({x_stop:.1f}px)}}}}")
    clip = f"fc{theme}"
    c.defs.append(f'<clipPath id="{clip}"><rect x="3" y="136" width="{W - 12}" height="{H - 148}" rx="12"/></clipPath>')
    ground = top + 2 * lh + 8
    c.add(f'<line x1="40" y1="{ground}" x2="{W - 48}" y2="{ground}" stroke="{t["subtle"]}" '
          f'stroke-width="1.5" stroke-dasharray="2 7" stroke-linecap="round"/>')
    c.add(f'<g clip-path="url(#{clip})"><g class="cat" style="animation:trot {period}s linear infinite">'
          f'<g style="animation:bob {2 * stride}s ease-in-out infinite">{cat}</g></g></g>')
    return c.render()


def frange(a, b, step):
    out, x = [], a
    while x < b - 1e-9:
        out.append(round(x, 4))
        x += step
    return out


PIECES = {
    "hero": hero, "work-head": work_head, "work-holt": holt, "work-sop-opera": sop_opera,
    "work-konta": konta, "work-flowsync": flowsync, "stack": stack, "footer": footer,
}


def main():
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.svg"):
        old.unlink()
    for theme in THEMES:
        for name, fn in PIECES.items():
            (OUT / f"{name}-{theme}.svg").write_text(fn(theme))
        for name, (kind, label) in BUTTONS.items():
            (OUT / f"btn-{name}-{theme}.svg").write_text(button(theme, kind, label))
    sizes = {p.name: p.stat().st_size // 1024 for p in sorted(OUT.glob("*.svg"))}
    print("  ".join(f"{k} {v}K" for k, v in sizes.items()))


if __name__ == "__main__":
    main()
