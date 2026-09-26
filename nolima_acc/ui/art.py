"""Generated artwork: rounded icon badges, rounded widget skins and glassmorphism panels.

Everything is drawn with Pillow at 4x resolution and scaled down, so edges are smooth
on any screen and no image files need to ship with the program.
"""
from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageTk

SS = 4  # supersampling factor

# One colour per area of the program (sidebar icons, tabs, KPI badges)
PALETTE = {
    "Dashboard": ("#10B981", "#047857"),
    "Sales": ("#3B82F6", "#1D4ED8"),
    "Purchases": ("#F59E0B", "#B45309"),
    "Banking": ("#06B6D4", "#0E7490"),
    "Items": ("#8B5CF6", "#6D28D9"),
    "Accounting": ("#EC4899", "#BE185D"),
    "Reports": ("#F97316", "#C2410C"),
    "Settings": ("#64748B", "#334155"),
}
TAB_COLOURS = ["#10B981", "#3B82F6", "#F59E0B", "#8B5CF6", "#EC4899", "#06B6D4", "#F97316", "#64748B"]

_keep = []  # PhotoImages must stay referenced or Tk drops them


def _hex(c, a=255):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


def photo(img):
    p = ImageTk.PhotoImage(img)
    _keep.append(p)
    return p


def rounded(w, h, r, fill, outline=None, width=1, shadow=0, shadow_alpha=40):
    """Rounded rectangle image (RGBA) with optional soft drop shadow."""
    pad = shadow * 2
    W, H = (w + pad) * SS, (h + pad) * SS
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle(
            [pad * SS // 2, pad * SS // 2 + shadow * SS // 2, (w + pad // 2) * SS, (h + pad // 2) * SS + shadow * SS // 2],
            r * SS, fill=(15, 42, 71, shadow_alpha))
        img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(shadow * SS * 0.7)))
    d = ImageDraw.Draw(img)
    box = [pad * SS // 2, pad * SS // 2, (w + pad // 2) * SS - 1, (h + pad // 2) * SS - 1]
    d.rounded_rectangle(box, r * SS, fill=_hex(fill) if isinstance(fill, str) else fill,
                        outline=_hex(outline) if isinstance(outline, str) else outline,
                        width=width * SS if outline else 0)
    return img.resize((w + pad, h + pad), Image.LANCZOS)


# ---------------------------------------------------------------- glyphs
def _glyph(d, name, s, col):
    """Draw a simple line icon filling an s x s area (already supersampled)."""
    w = max(2, int(s * 0.085))
    L = lambda pts: d.line(pts, fill=col, width=w, joint="curve")
    R = lambda b, rr=0.08: d.rounded_rectangle(b, int(s * rr), outline=col, width=w)
    F = lambda b, rr=0.05: d.rounded_rectangle(b, int(s * rr), fill=col)
    E = lambda b: d.ellipse(b, outline=col, width=w)
    p = lambda x, y: (s * x, s * y)
    if name == "Dashboard":
        for x, y, ww, hh in ((.18, .18, .28, .36), (.54, .18, .28, .22), (.18, .60, .28, .22), (.54, .46, .28, .36)):
            F([s * x, s * y, s * (x + ww), s * (y + hh)])
    elif name == "Sales":  # receipt with lines
        R([s * .24, s * .16, s * .76, s * .84])
        for y in (.34, .48, .62):
            L([p(.34, y), p(.66, y)])
    elif name == "Purchases":  # cart
        L([p(.14, .22), p(.26, .22), p(.34, .62), p(.74, .62), p(.82, .34), p(.30, .34)])
        for x in (.38, .68):
            d.ellipse([s * x - w * 1.3, s * .76 - w * 1.3, s * x + w * 1.3, s * .76 + w * 1.3], fill=col)
    elif name == "Banking":  # bank building
        d.polygon([p(.5, .14), p(.84, .34), p(.16, .34)], outline=col, width=w)
        for x in (.28, .44, .56, .72):
            L([p(x, .42), p(x, .70)])
        L([p(.16, .80), p(.84, .80)])
    elif name == "Items":  # box
        d.polygon([p(.5, .16), p(.84, .32), p(.84, .70), p(.5, .86), p(.16, .70), p(.16, .32)], outline=col, width=w)
        L([p(.16, .32), p(.5, .48), p(.84, .32)])
        L([p(.5, .48), p(.5, .86)])
    elif name == "Accounting":  # ledger book
        R([s * .22, s * .16, s * .78, s * .84])
        L([p(.36, .16), p(.36, .84)])
        for y in (.36, .50):
            L([p(.46, y), p(.68, y)])
    elif name == "Reports":  # bar chart
        for x, top in ((.24, .52), (.44, .30), (.64, .42)):
            F([s * x, s * top, s * (x + .13), s * .80], .03)
        L([p(.16, .84), p(.84, .84)])
    elif name == "Settings":  # gear
        import math
        cx = cy = s / 2
        for i in range(8):
            a = i * math.pi / 4
            d.line([(cx + math.cos(a) * s * .20, cy + math.sin(a) * s * .20),
                    (cx + math.cos(a) * s * .34, cy + math.sin(a) * s * .34)], fill=col, width=int(w * 1.6))
        E([s * .28, s * .28, s * .72, s * .72])
        E([s * .42, s * .42, s * .58, s * .58])
    elif name == "up":
        L([p(.5, .80), p(.5, .22)]); L([p(.28, .42), p(.5, .20), p(.72, .42)])
    elif name == "down":
        L([p(.5, .20), p(.5, .78)]); L([p(.28, .58), p(.5, .80), p(.72, .58)])
    elif name == "trend":
        L([p(.16, .70), p(.40, .46), p(.56, .58), p(.84, .28)]); L([p(.64, .28), p(.84, .28), p(.84, .46)])
    elif name == "wallet":
        R([s * .16, s * .28, s * .84, s * .78]); L([p(.24, .28), p(.66, .16), p(.72, .28)])
        d.ellipse([s * .62, s * .48, s * .72, s * .58], fill=col)
    elif name == "in":
        L([p(.2, .56), p(.2, .80), p(.8, .80), p(.8, .56)]); L([p(.5, .18), p(.5, .60)]); L([p(.34, .46), p(.5, .62), p(.66, .46)])
    elif name == "out":
        L([p(.2, .56), p(.2, .80), p(.8, .80), p(.8, .56)]); L([p(.5, .62), p(.5, .18)]); L([p(.34, .34), p(.5, .18), p(.66, .34)])
    elif name == "plus":
        L([p(.5, .24), p(.5, .76)]); L([p(.24, .5), p(.76, .5)])


@lru_cache(maxsize=None)
def badge_img(name, colours, size=34, radius=11, glyph=None):
    """Rounded, gradient-filled square badge with a white glyph (PIL image)."""
    top, bottom = colours
    S = size * SS
    grad = Image.new("RGBA", (S, S))
    t, b = _hex(top), _hex(bottom)
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        k = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(int(t[i] + (b[i] - t[i]) * k) for i in range(3)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius * SS, fill=255)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    # soft top highlight for a raised, glossy feel
    hl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(hl).rounded_rectangle([SS, SS, S - SS, S // 2], radius * SS, fill=(255, 255, 255, 38))
    out = Image.alpha_composite(out, Image.composite(hl, Image.new("RGBA", (S, S), (0, 0, 0, 0)), mask))
    g = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    inset = int(S * 0.2)
    gi = Image.new("RGBA", (S - 2 * inset, S - 2 * inset), (0, 0, 0, 0))
    _glyph(ImageDraw.Draw(gi), glyph or name, S - 2 * inset, (255, 255, 255, 255))
    g.paste(gi, (inset, inset))
    out = Image.alpha_composite(out, g)
    return out.resize((size, size), Image.LANCZOS)


def badge(name, size=34, colours=None, glyph=None):
    return photo(badge_img(name, colours or PALETTE.get(name, PALETTE["Settings"]), size, max(8, size // 3), glyph))


# ---------------------------------------------------------------- ttk skins
def install_skins(style, C):
    """Rounded buttons, entry fields, comboboxes and card panels for ttk."""
    def btn(fill, border, name):
        img = rounded(40, 36, 10, fill, border)
        return photo(img)

    variants = {
        "": ("#FFFFFF", "#D3DCE6", "#EEF3F8", "#D3DCE6", "#E2E9F0", "#F4F6F8"),
        "Primary.": (C.EMERALD, C.EMERALD, C.EMERALD_2, C.EMERALD_2, "#166A4D", "#9BBFB1"),
        "Danger.": ("#FFFFFF", "#F1C4BF", "#FDF1EF", "#E8A59C", "#FBE3DF", "#F4F6F8"),
    }
    for prefix, (n, nb, h, hb, pr, dis) in variants.items():
        normal, hover = btn(n, nb, "n"), btn(h, hb, "h")
        pressed, disabled = btn(pr, pr, "p"), btn(dis, dis, "d")
        el = f"{prefix or 'Plain.'}RBtn.border"
        style.element_create(el, "image", normal, ("disabled", disabled), ("pressed", pressed), ("active", hover),
                             border=(12, 8), sticky="nsew")
        layout = [(el, {"sticky": "nsew", "children": [
            ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})]
        style.layout(f"{prefix}TButton", layout)

    field = photo(rounded(40, 34, 8, "#FFFFFF", "#CBD5E1"))
    focus = photo(rounded(40, 34, 8, "#FFFFFF", C.EMERALD, width=2))
    ro = photo(rounded(40, 34, 8, "#F1F5F9", "#CBD5E1"))
    style.element_create("R.field", "image", field, ("focus", focus), ("readonly", "!focus", ro),
                         ("disabled", ro), border=(9, 7), sticky="nsew")
    style.layout("TEntry", [("R.field", {"sticky": "nsew", "border": "1", "children": [
        ("Entry.padding", {"sticky": "nsew", "children": [("Entry.textarea", {"sticky": "nsew"})]})]})])
    style.element_create("RC.field", "image", field, ("focus", focus), border=(9, 7), sticky="nsew")
    style.layout("TCombobox", [("RC.field", {"sticky": "nsew", "children": [
        ("Combobox.downarrow", {"side": "right", "sticky": "ns"}),
        ("Combobox.padding", {"expand": "1", "sticky": "nsew", "children": [
            ("Combobox.textarea", {"sticky": "nsew"})]})]})])
    style.layout("TSpinbox", [("R.field", {"sticky": "nsew", "children": [
        ("null", {"side": "right", "sticky": "ns", "children": [
            ("Spinbox.uparrow", {"side": "top", "sticky": "e"}),
            ("Spinbox.downarrow", {"side": "bottom", "sticky": "e"})]}),
        ("Spinbox.padding", {"sticky": "nsew", "children": [("Spinbox.textarea", {"sticky": "nsew"})]})]})])

    panel = photo(rounded(64, 64, 16, "#FFFFFF", "#E3E9F0", shadow=6, shadow_alpha=28))
    style.element_create("Panel.bg", "image", panel, border=24, sticky="nsew")
    style.layout("Panel.TFrame", [("Panel.bg", {"sticky": "nsew"})])


# ---------------------------------------------------------------- glass
@lru_cache(maxsize=4)
def glass_backdrop(w, h):
    """Deep navy gradient with blurred colour blobs: the scene the glass panels float over.
    Drawn at quarter size and scaled up: it is all soft blur, so nothing is lost and it is much faster."""
    q = 4
    sw, sh = max(8, w // q), max(8, h // q)
    grad = Image.new("RGB", (1, 256))
    a, b = _hex("#0B2340"), _hex("#0E3B4A")
    for y in range(256):
        k = y / 255
        grad.putpixel((0, y), tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3)))
    img = grad.resize((sw, sh), Image.BILINEAR).convert("RGBA")
    blobs = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blobs)
    for cx, cy, r, col in ((.12, .18, .30, "#10B981"), (.80, .10, .28, "#3B82F6"), (.62, .78, .34, "#8B5CF6"),
                           (.18, .92, .26, "#06B6D4"), (.95, .62, .22, "#EC4899")):
        R = int(r * max(sw, sh) * 0.55)
        bd.ellipse([cx * sw - R, cy * sh - R, cx * sw + R, cy * sh + R], fill=_hex(col, 150))
    blobs = blobs.filter(ImageFilter.GaussianBlur(max(sw, sh) * 0.07))
    return Image.alpha_composite(img, blobs).resize((w, h), Image.BICUBIC)


@lru_cache(maxsize=4)
def _frosted(w, h):
    """The whole backdrop blurred once; every glass panel is cut from it."""
    small = glass_backdrop(w, h).resize((max(4, w // 2), max(4, h // 2)), Image.BILINEAR)
    return small.filter(ImageFilter.GaussianBlur(7)).resize((w, h), Image.BILINEAR)


@lru_cache(maxsize=6)
def compose_glass(w, h, boxes, radius=18):
    """Backdrop with frosted-glass panels at each (x0, y0, x1, y1) box.
    Blurs happen once per window size (not once per panel) and results are cached."""
    boxes = tuple(tuple(int(v) for v in b) for b in boxes)
    base = glass_backdrop(w, h).copy()
    frosted = _frosted(w, h)
    sh = Image.new("L", (max(4, w // 2), max(4, h // 2)), 0)
    sd = ImageDraw.Draw(sh)
    for (x0, y0, x1, y1) in boxes:
        if x1 - x0 >= 4 and y1 - y0 >= 4:
            sd.rounded_rectangle([(x0 + 2) // 2, (y0 + 8) // 2, (x1 + 2) // 2, (y1 + 10) // 2], radius // 2, fill=70)
    sh = sh.filter(ImageFilter.GaussianBlur(5)).resize((w, h), Image.BILINEAR)
    base = Image.composite(Image.new("RGBA", (w, h), (3, 12, 28, 255)), base, sh)
    for (x0, y0, x1, y1) in boxes:
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        region = Image.alpha_composite(frosted.crop((x0, y0, x1, y1)),
                                       Image.new("RGBA", (x1 - x0, y1 - y0), (255, 255, 255, 34)))
        mask = Image.new("L", (region.width * 2, region.height * 2), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, mask.width - 1, mask.height - 1], radius * 2, fill=255)
        mask = mask.resize(region.size, Image.BILINEAR)
        base.paste(region, (x0, y0), mask)
        edge = Image.new("RGBA", region.size, (0, 0, 0, 0))
        ed = ImageDraw.Draw(edge)
        ed.rounded_rectangle([0, 0, edge.width - 1, edge.height - 1], radius, outline=(255, 255, 255, 90), width=1)
        hh = max(2, edge.height // 3)
        for yy in range(hh):
            a = int(16 * (1 - yy / hh) ** 2)
            if a:
                ed.line([(radius // 2, 1 + yy), (edge.width - radius // 2, 1 + yy)], fill=(255, 255, 255, a))
        base.alpha_composite(edge, (x0, y0))
    return base


def pill(w, h, fill, outline=None, width=1):
    return photo(rounded(w, h, h // 2, fill, outline, width))
