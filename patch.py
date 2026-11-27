#!/usr/bin/env python3
"""
Patch the Go fonts (golang.org/x/image/font/gofont/ttfs, v2.010).

1. Remove TrueType hinting (fontTools only, no ttfautohint / pyftsubset),
   remove the unencoded glyphs zero.dot / zero.empty,
   drop the legacy Mac (platform 1) cmap subtable and name records,
   set version to 3.002.
2. Fix Medium naming (nameID 16/17) and unify PostScript names.
3. Set usWeightClass = 700 for all Bold / Bold Italic faces.
4. Move U+00B7 (periodcentered) to y = 740 (half the cap height 1480).

Usage: python3 patch.py SRC_DIR OUT_DIR
"""
import math
import os
import sys
from fontTools.ttLib import TTFont

# file -> (PostScript name, typographic family, typographic subfamily or None)
FONTS = {
    "Go-Regular.ttf":          ("Go-Regular",        "Go",      None),
    "Go-Italic.ttf":           ("Go-Italic",         "Go",      None),
    "Go-Medium.ttf":           ("Go-Medium",         "Go",      "Medium"),
    "Go-Medium-Italic.ttf":    ("Go-MediumItalic",   "Go",      "Medium Italic"),
    "Go-Bold.ttf":             ("Go-Bold",           "Go",      None),
    "Go-Bold-Italic.ttf":      ("Go-BoldItalic",     "Go",      None),
    "Go-Mono.ttf":             ("GoMono-Regular",    "Go Mono", None),
    "Go-Mono-Italic.ttf":      ("GoMono-Italic",     "Go Mono", None),
    "Go-Mono-Bold.ttf":        ("GoMono-Bold",       "Go Mono", None),
    "Go-Mono-Bold-Italic.ttf": ("GoMono-BoldItalic", "Go Mono", None),
}
DROP_GLYPHS = {"zero.dot", "zero.empty"}
HINT_TABLES = ("fpgm", "prep", "cvt ", "hdmx", "LTSH", "VDMX")
VERSION = 3.002
PLATFORMS = [(3, 1, 0x409)]  # Windows Unicode / en-US only


def set_name(font, name_id, value):
    for plat, enc, lang in PLATFORMS:
        font["name"].setName(value, name_id, plat, enc, lang)


def remove_hinting(font):
    for tag in HINT_TABLES:
        if tag in font:
            del font[tag]
    glyf = font["glyf"]
    for name in font.getGlyphOrder():
        g = glyf[name]
        g.expand(glyf)
        g.removeHinting()
    maxp = font["maxp"]
    maxp.maxZones = 1
    for attr in ("maxTwilightPoints", "maxStorage", "maxFunctionDefs",
                 "maxInstructionDefs", "maxStackElements", "maxSizeOfInstructions"):
        setattr(maxp, attr, 0)
    # Unhinted: smoothing + symmetric smoothing at every size, no grid-fitting.
    font["gasp"].gaspRange = {0xFFFF: 0x000A}


def drop_mac_cmap(font):
    """Remove the legacy Mac Roman (platform 1) cmap subtable."""
    cmap = font["cmap"]
    cmap.tables = [t for t in cmap.tables if t.platformID != 1]


def drop_mac_names(font):
    """Remove the legacy Mac (platform 1) name records."""
    name = font["name"]
    name.names = [n for n in name.names if n.platformID != 1]


def remove_glyphs(font, drop):
    order = font.getGlyphOrder()
    drop = [g for g in order if g in drop]
    if not drop:
        return
    glyf = font["glyf"]
    # Make sure nothing still references the glyphs we drop.
    for name in order:
        g = glyf[name]
        if g.isComposite():
            used = {c.glyphName for c in g.components} & set(drop)
            if used:
                sys.exit(f"{name} uses {used} as a component; refusing to drop")
    for sub in font["cmap"].tables:
        if set(sub.cmap.values()) & set(drop):
            sys.exit(f"cmap still maps {drop}; refusing to drop")
    for name in drop:
        del glyf.glyphs[name]
        del font["hmtx"].metrics[name]
    new_order = [g for g in order if g not in drop]
    glyf.glyphOrder = new_order
    font.setGlyphOrder(new_order)  # maxp.numGlyphs follows this on save
    # post format 2 keeps its old extraNames list on compile; clear it so it is
    # rebuilt from the new glyph order and the dropped names are not left behind.
    post = font["post"]
    if post.formatType == 2.0:
        post.extraNames = []
        post.mapping = {}


DOT_CENTER = 740  # half of the cap height 1480 shared by every Go font


def center_middle_dot(font):
    """Move U+00B7 so its vertical center sits at DOT_CENTER; shift along the italic slant."""
    cmap = font.getBestCmap()
    glyf = font["glyf"]
    dot = glyf[cmap[0xB7]]
    dy = DOT_CENTER - (dot.yMin + dot.yMax) // 2
    dx = round(-dy * math.tan(math.radians(font["post"].italicAngle)))
    dot.coordinates.translate((dx, dy))
    dot.recalcBounds(glyf)
    font["hmtx"][cmap[0xB7]] = (font["hmtx"][cmap[0xB7]][0], dot.xMin)


def set_version(font, version):
    font["head"].fontRevision = version
    set_name(font, 5, f"Version {version:.3f}")


def main(src, out):
    os.makedirs(out, exist_ok=True)
    for fname, (ps_name, typo_family, typo_sub) in FONTS.items():
        font = TTFont(os.path.join(src, fname))
        font.ensureDecompiled()

        remove_hinting(font)
        drop_mac_cmap(font)
        drop_mac_names(font)
        remove_glyphs(font, DROP_GLYPHS)
        center_middle_dot(font)
        set_version(font, VERSION)

        set_name(font, 6, ps_name)
        if typo_sub:  # Medium: group under "Go"; legacy nameID 1/2 kept
            set_name(font, 16, typo_family)
            set_name(font, 17, typo_sub)

        if "Bold" in fname:
            font["OS/2"].usWeightClass = 700

        font.save(os.path.join(out, fname))
        print(f"{fname}: ps={ps_name} weight={font['OS/2'].usWeightClass} "
              f"glyphs={len(font.getGlyphOrder())}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
