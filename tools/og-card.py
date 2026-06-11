#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
og-card.py — Share-Card (1200×630) für einen Artikel generieren.
Benötigt Pillow:  pip install pillow

Aufruf (vom Repo-Root):
  python tools/og-card.py --slug rtx-spark-im-check \
    --titel "RTX Spark im Check: Revolution oder Hype?" \
    --tag ANALYSE [--datum "10. Juni 2026"]

Ausgabe: artikel/<slug>-og.png
Dann im Artikel og:image + twitter:image auf
https://ki-news.live/artikel/<slug>-og.png setzen
(macht neuer-artikel.py automatisch, wenn die Card existiert).
"""
import argparse, os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1200, 630
ACCENT = (0, 212, 255)
BG = (4, 8, 14)

def font(path, size):
    return ImageFont.truetype(os.path.join(ROOT, "assets", "fonts", path), size)

def wrap(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=fnt) <= max_w:
            cur = t
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--titel", required=True)
    ap.add_argument("--tag", default="ANALYSE")
    ap.add_argument("--datum", default="")
    a = ap.parse_args()

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Hintergrund: dezentes Punktraster + Glow unten
    for y in range(0, H, 28):
        for x in range(0, W, 28):
            d.ellipse([x, y, x + 2, y + 2], fill=(14, 26, 40))
    for i in range(120):
        alpha = int(40 * (1 - i / 120))
        d.line([(0, H - i), (W, H - i)], fill=(0, int(212 * alpha / 255 * 0.3), int(255 * alpha / 255 * 0.3)))

    # Akzentbalken links
    d.rectangle([0, 0, 14, H], fill=ACCENT)

    # Logo (s-logo.png) oben links
    try:
        logo = Image.open(os.path.join(ROOT, "s-logo.png")).convert("RGBA").resize((72, 72))
        img.paste(logo, (64, 56), logo)
    except Exception:
        pass
    d.text((152, 62), "KI NEWS", font=font("SpaceGrotesk-Variable.ttf", 40), fill=ACCENT)
    d.text((152, 106), "KI-NEWS.LIVE · TÄGLICH AUF DEUTSCH", font=font("SpaceGrotesk-Variable.ttf", 17), fill=(110, 140, 165))

    # Tag-Badge
    tag_f = font("SpaceGrotesk-Variable.ttf", 22)
    tw = d.textlength(a.tag.upper(), font=tag_f)
    d.rounded_rectangle([64, 196, 64 + tw + 36, 240], radius=6, fill=ACCENT)
    d.text((82, 204), a.tag.upper(), font=tag_f, fill=(0, 0, 0))

    # Titel (max 4 Zeilen)
    title_f = font("SpaceGrotesk-Variable.ttf", 62)
    lines = wrap(d, a.titel, title_f, W - 64 - 80)[:4]
    y = 278
    for ln in lines:
        d.text((64, y), ln, font=title_f, fill=(235, 245, 252))
        y += 74

    # Fußzeile
    foot = ("@ScampyKI" + (" · " + a.datum if a.datum else ""))
    d.text((64, H - 70), foot, font=font("SpaceGrotesk-Variable.ttf", 24), fill=(110, 140, 165))

    out = os.path.join(ROOT, "artikel", a.slug + "-og.png")
    img.save(out, "PNG", optimize=True)
    print("✓", os.path.relpath(out, ROOT))

if __name__ == "__main__":
    main()
