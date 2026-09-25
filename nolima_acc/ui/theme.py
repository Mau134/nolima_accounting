"""Look and feel: Nolima navy/emerald, Space Grotesk (bundled) with Segoe UI fallback."""
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from .. import config as C

FAMILY = "Segoe UI"


def load_fonts(root):
    """Register bundled Space Grotesk privately on Windows; use it if Tk can see it."""
    global FAMILY
    fonts_dir = C.resource_path("assets", "fonts")
    if os.name == "nt":
        try:
            import ctypes
            for f in fonts_dir.glob("*.ttf"):
                ctypes.windll.gdi32.AddFontResourceExW(str(f), 0x10, 0)
        except Exception:
            pass
    families = set(tkfont.families(root))
    for cand in ("Space Grotesk", "Segoe UI", "Helvetica Neue", "DejaVu Sans", "Arial"):
        if cand in families:
            FAMILY = cand
            break
    return FAMILY


def f(size=10, weight="normal"):
    """Pixel-based sizes so the layout looks the same at any screen DPI."""
    return (FAMILY, -round(size * 1.4), weight)


def money(v, blank_zero=False):
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return str(v)
    if blank_zero and abs(v) < 0.005:
        return ""
    return f"({abs(v):,.2f})" if v < -0.004 else f"{v:,.2f}"


def apply(root):
    load_fonts(root)
    root.configure(bg=C.BG)
    fam, px, _ = f(10)
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(name).configure(family=fam, size=px)
        except tk.TclError:
            pass
    root.option_add("*TCombobox*Listbox.font", f(10))
    s = ttk.Style(root)
    try:
        s.theme_use("clam")
    except tk.TclError:
        pass
    s.configure(".", font=f(10), background=C.BG, foreground=C.TEXT, bordercolor=C.LINE)
    s.configure("TFrame", background=C.BG)
    s.configure("Card.TFrame", background=C.CARD, relief="flat")
    s.configure("TLabel", background=C.BG, foreground=C.TEXT)
    s.configure("Card.TLabel", background=C.CARD)
    s.configure("Muted.TLabel", background=C.BG, foreground=C.MUTED)
    s.configure("CardMuted.TLabel", background=C.CARD, foreground=C.MUTED, font=f(9))
    s.configure("H1.TLabel", font=f(18, "bold"), background=C.BG)
    s.configure("H2.TLabel", font=f(12, "bold"), background=C.CARD)
    s.configure("KPI.TLabel", font=f(13, "bold"), background=C.CARD)
    s.configure("TButton", font=f(10, "bold"), padding=(6, 1), foreground=C.NAVY, background=C.BG)
    s.map("TButton", foreground=[("disabled", "#9AA8B6")])
    s.configure("Primary.TButton", foreground="white", background=C.BG)
    s.map("Primary.TButton", foreground=[("disabled", "#EEF4F1")])
    s.configure("Danger.TButton", foreground=C.DANGER, background=C.BG)
    s.configure("TEntry", padding=(3, 1), fieldbackground="white", background=C.CARD, foreground=C.TEXT)
    s.configure("TCombobox", padding=(3, 1), fieldbackground="white", background=C.CARD, arrowcolor=C.MUTED,
                arrowsize=14)
    s.map("TCombobox", fieldbackground=[("readonly", "white")], selectbackground=[("readonly", "white")],
          selectforeground=[("readonly", C.TEXT)])
    s.configure("TSpinbox", padding=(3, 1), fieldbackground="white", background=C.CARD, arrowsize=12)
    s.configure("Panel.TFrame", background=C.BG, padding=22)
    from . import art
    art.install_skins(s, C)
    s.configure("Treeview", font=f(10), rowheight=34, background="white", fieldbackground="white",
                bordercolor="white", borderwidth=0, relief="flat")
    s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    s.configure("Treeview.Heading", font=f(9, "bold"), background="#EEF2F7", foreground="#475569",
                relief="flat", padding=(8, 9), borderwidth=0)
    s.map("Treeview.Heading", background=[("active", "#E2E8F0")])
    s.configure("Vertical.TScrollbar", background="#CBD5E1", troughcolor="white", bordercolor="white",
                arrowcolor=C.MUTED, gripcount=0, relief="flat")
    s.map("Treeview", background=[("selected", "#CFE8DD")], foreground=[("selected", C.NAVY)])
    s.configure("TNotebook", background=C.BG, borderwidth=0)
    s.configure("TNotebook.Tab", font=f(10), padding=(16, 7), background="#E3EAF0")
    s.map("TNotebook.Tab", background=[("selected", C.CARD)], foreground=[("selected", C.EMERALD)])
    s.configure("TCheckbutton", background=C.BG)
    s.configure("Card.TCheckbutton", background=C.CARD)
    s.configure("TLabelframe", background=C.CARD)
    return s
