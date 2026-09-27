"""Reusable widgets: tables, forms, document line editor, charts, logo."""
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from .. import config as C
from .theme import f, money


def draw_logo(canvas, x, y, s=1.0):
    """Nolima shield with networked N (same mark as Nolima Store)."""
    pts = [x, y + 8 * s, x + 19 * s, y, x + 38 * s, y + 8 * s, x + 38 * s, y + 30 * s,
           x + 19 * s, y + 54 * s, x, y + 30 * s]
    canvas.create_polygon(pts, fill=C.EMERALD, outline="", smooth=False)
    n = [(x + 11 * s, y + 40 * s), (x + 11 * s, y + 14 * s), (x + 27 * s, y + 40 * s), (x + 27 * s, y + 14 * s)]
    for a, b in zip(n, n[1:]):
        canvas.create_line(*a, *b, fill="white", width=max(2, int(2.6 * s)))
    for px, py in n:
        r = 3 * s
        canvas.create_oval(px - r, py - r, px + r, py + r, fill="white", outline="")


def error(parent, msg, title="Nolima Accounting"):
    messagebox.showerror(title, str(msg), parent=parent)


def info(parent, msg, title="Nolima Accounting"):
    messagebox.showinfo(title, str(msg), parent=parent)


def confirm(parent, msg, title="Please confirm"):
    return messagebox.askyesno(title, msg, parent=parent)


def valid_date(text):
    try:
        date.fromisoformat(text.strip())
        return True
    except ValueError:
        return False


def num(text, default=0.0):
    try:
        return float(str(text).replace(",", "").strip() or default)
    except ValueError:
        raise ValueError(f"'{text}' is not a valid number.")


class Card(ttk.Frame):
    """White rounded panel with a soft shadow."""

    def __init__(self, parent, title=None, **kw):
        super().__init__(parent, style="Panel.TFrame", padding=22, **kw)
        if title:
            ttk.Label(self, text=title, style="H2.TLabel").pack(anchor="w", pady=(0, 10))


def tint(colour, k=0.88):
    """Mix a colour with white (k = share of white)."""
    c = colour.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02X%02X%02X" % tuple(int(v + (255 - v) * k) for v in (r, g, b))


class ColorTabs(ttk.Frame):
    """Tab control whose tabs are rounded pills, each in its own colour."""

    def __init__(self, parent, colours=None):
        super().__init__(parent)
        from . import art
        self.art = art
        self.colours = colours or art.TAB_COLOURS
        self.bar = tk.Frame(self, bg=C.BG)
        self.bar.pack(fill="x", pady=(0, 14))
        self.tabs = []
        self.index = None

    def add(self, child, text):
        i = len(self.tabs)
        col = self.colours[i % len(self.colours)]
        lbl = tk.Label(self.bar, bd=0, bg=C.BG, cursor="hand2", compound="center", font=f(10, "bold"),
                       highlightthickness=0)
        lbl.pack(side="left", padx=(0, 8))
        lbl.bind("<Button-1>", lambda e, k=i: self.select(k))
        lbl.bind("<Enter>", lambda e, k=i: self._paint(k, hover=True))
        lbl.bind("<Leave>", lambda e, k=i: self._paint(k))
        self.tabs.append({"child": child, "text": text, "col": col, "lbl": lbl, "img": {}})
        self._paint(i)
        if self.index is None:
            self.select(0)

    def _img(self, t, state):
        if state not in t["img"]:
            import tkinter.font as tkfont
            w = tkfont.Font(font=f(10, "bold")).measure(t["text"]) + 40
            if state == "sel":
                t["img"][state] = self.art.pill(w, 36, t["col"])
            elif state == "hover":
                t["img"][state] = self.art.pill(w, 36, tint(t["col"], 0.78))
            else:
                t["img"][state] = self.art.pill(w, 36, tint(t["col"], 0.90))
        return t["img"][state]

    def _paint(self, i, hover=False):
        t = self.tabs[i]
        state = "sel" if i == self.index else ("hover" if hover else "idle")
        fg = "white" if state == "sel" else self._dark(t["col"])
        t["lbl"].configure(image=self._img(t, state), text=t["text"], fg=fg)

    @staticmethod
    def _dark(col):
        c = col.lstrip("#")
        return "#%02X%02X%02X" % tuple(int(int(c[i:i + 2], 16) * 0.62) for i in (0, 2, 4))

    def select(self, i):
        if self.index is not None:
            self.tabs[self.index]["child"].pack_forget()
        prev, self.index = self.index, i
        self.tabs[i]["child"].pack(fill="both", expand=True)
        for k in range(len(self.tabs)):
            self._paint(k)
        self.event_generate("<<TabChanged>>")


class Table(ttk.Frame):
    """Treeview with scrollbars. columns: [(key, heading, width, anchor)]"""

    def __init__(self, parent, columns, height=15, on_double=None, money_cols=(), **kw):
        super().__init__(parent, **kw)
        self.columns = columns
        self.money_cols = set(money_cols)
        self.tree = ttk.Treeview(self, columns=[c[0] for c in columns], show="headings", height=height,
                                 selectmode="browse")
        for key, head, width, anchor in columns:
            self.tree.heading(key, text=head, command=lambda k=key: self._sort(k))
            self.tree.column(key, width=width, anchor=anchor, stretch=anchor == "w")
        vs = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.tree.tag_configure("odd", background="#F7FAFC")
        self.tree.tag_configure("bold", font=f(10, "bold"))
        self.tree.tag_configure("red", foreground=C.DANGER)
        self.tree.tag_configure("muted", foreground=C.MUTED)
        if on_double:
            self.tree.bind("<Double-1>", lambda e: on_double(self.selected()))
        self._asc = {}

    def set_rows(self, rows, ids=None, tags=None):
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(rows):
            vals = [money(v) if self.columns[j][0] in self.money_cols and isinstance(v, (int, float)) else
                    ("" if v is None else v) for j, v in enumerate(r)]
            t = list(tags[i]) if tags and tags[i] else []
            if i % 2:
                t.append("odd")
            iid = str(ids[i]) if ids else None
            self.tree.insert("", "end", iid=iid, values=vals, tags=t)

    def selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def rows(self):
        return [self.tree.item(i, "values") for i in self.tree.get_children()]

    def _sort(self, key):
        items = [(self.tree.set(i, key), i) for i in self.tree.get_children("")]
        asc = not self._asc.get(key, False)
        self._asc[key] = asc

        def k(v):
            s = v[0].replace(",", "").replace("(", "-").replace(")", "")
            try:
                return (0, float(s))
            except ValueError:
                return (1, v[0].lower())
        items.sort(key=k, reverse=not asc)
        for idx, (_, i) in enumerate(items):
            self.tree.move(i, "", idx)


class Dialog(tk.Toplevel):
    def __init__(self, parent, title, width=None):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.configure(bg=C.CARD)
        self.transient(parent.winfo_toplevel())
        self.resizable(True, True)
        self.result = None
        self.body = ttk.Frame(self, style="Card.TFrame", padding=20)
        self.body.pack(fill="both", expand=True)
        self.buttons = ttk.Frame(self, style="Card.TFrame", padding=(20, 0, 20, 16))
        self.buttons.pack(fill="x")
        self.bind("<Escape>", lambda e: self.destroy())
        self._width = width

    def show(self):
        self.update_idletasks()
        p = self.master.winfo_toplevel()
        w = max(self.winfo_reqwidth(), self._width or 0)
        h = self.winfo_reqheight()
        x = p.winfo_rootx() + max(0, (p.winfo_width() - w) // 2)
        y = p.winfo_rooty() + max(0, (p.winfo_height() - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.deiconify()
        self.grab_set()
        self.focus_set()
        self.wait_window()
        return self.result


class FormDialog(Dialog):
    """fields: [(key, label, kind, options, default)]
    kinds: entry, password, number, date, combo (options=[(value,label)]), check, text, readonly"""

    def __init__(self, parent, title, fields, on_submit=None, width=460, ok_text="Save"):
        super().__init__(parent, title, width)
        self.vars, self.widgets, self.fields = {}, {}, fields
        self.on_submit = on_submit
        per_col = (len(fields) + 1) // 2 if len(fields) > 10 else len(fields)  # long forms: two columns
        for n, fld in enumerate(fields):
            r, block = n % per_col, n // per_col
            key, label, kind = fld[0], fld[1], fld[2]
            options = fld[3] if len(fld) > 3 else None
            default = fld[4] if len(fld) > 4 else None
            ttk.Label(self.body, text=label, style="CardMuted.TLabel", wraplength=230).grid(
                row=r, column=2 * block, sticky="nw", pady=5, padx=(24 if block else 0, 12))
            if kind == "check":
                v = tk.BooleanVar(value=bool(default))
                w = ttk.Checkbutton(self.body, variable=v, style="Card.TCheckbutton")
            elif kind == "combo":
                v = tk.StringVar()
                labels = [o[1] for o in options]
                w = ttk.Combobox(self.body, textvariable=v, values=labels, state="readonly", width=34)
                if default is not None:
                    for o in options:
                        if o[0] == default:
                            v.set(o[1])
                elif labels:
                    v.set(labels[0])
            elif kind == "text":
                v = None
                w = tk.Text(self.body, height=3, width=36, font=f(10), relief="solid", bd=1,
                            highlightthickness=0)
                if default:
                    w.insert("1.0", default)
            else:
                v = tk.StringVar(value="" if default is None else str(default))
                w = ttk.Entry(self.body, textvariable=v, width=36, show="\u2022" if kind == "password" else "")
                if kind == "readonly":
                    w.state(["readonly"])
                if kind == "date" and not default:
                    v.set(date.today().isoformat())
            w.grid(row=r, column=2 * block + 1, sticky="ew", pady=5)
            self.vars[key], self.widgets[key] = v, w
        self.body.columnconfigure(1, weight=1)
        if per_col < len(fields):
            self.body.columnconfigure(3, weight=1)
        ttk.Button(self.buttons, text=ok_text, style="Primary.TButton", command=self._ok).pack(side="right")
        ttk.Button(self.buttons, text="Cancel", command=self.destroy).pack(side="right", padx=8)
        self.bind("<Return>", lambda e: self._ok() if not isinstance(e.widget, tk.Text) else None)
        first = self.widgets[fields[0][0]] if fields else None
        if first is not None:
            self.after(50, first.focus_set)

    def values(self):
        out = {}
        for fld in self.fields:
            key, kind = fld[0], fld[2]
            v, w = self.vars[key], self.widgets[key]
            if kind == "check":
                out[key] = v.get()
            elif kind == "combo":
                lab = v.get()
                out[key] = next((o[0] for o in fld[3] if o[1] == lab), None)
            elif kind == "text":
                out[key] = w.get("1.0", "end").strip()
            elif kind == "number":
                out[key] = num(v.get())
            elif kind == "date":
                if not valid_date(v.get()):
                    raise ValueError(f"{fld[1]}: use the date format YYYY-MM-DD.")
                out[key] = v.get().strip()
            else:
                out[key] = v.get().strip()
        return out

    def _ok(self):
        try:
            vals = self.values()
            if self.on_submit:
                res = self.on_submit(vals)
                self.result = res if res is not None else vals
            else:
                self.result = vals
        except Exception as exc:  # show validation errors, keep dialog open
            error(self, exc)
            return
        self.destroy()


class LinesEditor(ttk.Frame):
    """Grid of document lines with an entry row. mode 'sale' | 'bill' | 'expense' | 'journal'."""

    def __init__(self, parent, books, mode="sale"):
        super().__init__(parent, style="Card.TFrame")
        self.books, self.mode = books, mode
        self.lines = []
        vat = books.vat_rate
        self.vat_opts = [f"{vat:g}%", "0%"]
        items = books.items()
        if mode == "sale":
            accts = books.accounts(types=["income"])
        elif mode in ("bill", "expense"):
            # expense accounts first; other accounts after, clearly marked, so nobody picks
            # "Cash on Hand" or "Inventory" by mistake for an ordinary expense
            accts = list(books.accounts(types=["expense"])) + \
                [a for a in books.accounts(types=["asset", "liability"])
                 if a["subtype"] not in ("bank", "cash", "receivable", "payable")]
        else:
            accts = books.accounts()
        self.item_opts = [(None, "")] + [(i["id"], f"{i['name']}") for i in items] if mode in ("sale", "bill") else []
        self.items_by_id = {i["id"]: i for i in items}
        self.acct_types = {a["id"]: a["type"] for a in accts}
        suffix = {"asset": "   (asset, not an expense)", "liability": "   (payment of a liability)"}
        self.acct_opts = [(a["id"], f"{a['code']}  {a['name']}" +
                           (suffix.get(a["type"], "") if mode in ("bill", "expense") else "")) for a in accts]
        self.show_depts = books.has_module("departments") and bool(books.departments())
        self.dept_opts = [(None, "")] + [(d["id"], d["name"]) for d in books.departments()]

        row = ttk.Frame(self, style="Card.TFrame")
        row.pack(fill="x", pady=(0, 6))
        self.v = {k: tk.StringVar() for k in ("item", "desc", "acct", "qty", "price", "vat", "dept", "dr", "cr",
                                              "disc", "ldate")}
        col = 0

        def add(label, widget, width=None):
            nonlocal col
            ttk.Label(row, text=label, style="CardMuted.TLabel").grid(row=0, column=col, sticky="w", padx=2)
            widget.grid(row=1, column=col, sticky="ew", padx=2)
            col += 1

        if self.item_opts:
            cb = ttk.Combobox(row, textvariable=self.v["item"], values=[o[1] for o in self.item_opts],
                              state="readonly", width=12)
            cb.bind("<<ComboboxSelected>>", self._item_chosen)
            add("Item", cb)
        if mode == "sale":
            add("Date", ttk.Entry(row, textvariable=self.v["ldate"], width=9))
        add("Description", ttk.Entry(row, textvariable=self.v["desc"], width=13))
        add("Account", ttk.Combobox(row, textvariable=self.v["acct"], values=[o[1] for o in self.acct_opts],
                                    state="readonly", width=14 if mode == "sale" else 19))
        if mode == "journal":
            add("Debit", ttk.Entry(row, textvariable=self.v["dr"], width=12))
            add("Credit", ttk.Entry(row, textvariable=self.v["cr"], width=12))
        elif mode == "expense":
            add("Amount (incl. VAT)", ttk.Entry(row, textvariable=self.v["price"], width=14))
            add("VAT", ttk.Combobox(row, textvariable=self.v["vat"], values=self.vat_opts, width=7, state="readonly"))
        else:
            add("Qty", ttk.Entry(row, textvariable=self.v["qty"], width=6))
            add("Unit price", ttk.Entry(row, textvariable=self.v["price"], width=9))
            add("Disc %", ttk.Entry(row, textvariable=self.v["disc"], width=5))
            add("VAT", ttk.Combobox(row, textvariable=self.v["vat"], values=self.vat_opts, width=7, state="readonly"))
        if self.show_depts:
            add("Department", ttk.Combobox(row, textvariable=self.v["dept"], values=[o[1] for o in self.dept_opts],
                                           state="readonly", width=11))
        ttk.Button(row, text="Add line", style="Primary.TButton", command=self.add_line).grid(row=1, column=col, padx=4)
        self.v["qty"].set("1")
        self.v["vat"].set(self.vat_opts[0])

        if mode == "journal":
            cols = [("acct", "Account", 240, "w"), ("desc", "Description", 200, "w"), ("dr", "Debit", 110, "e"),
                    ("cr", "Credit", 110, "e")]
        elif mode == "expense":
            cols = [("acct", "Account", 240, "w"), ("desc", "Description", 200, "w"), ("amt", "Amount", 110, "e"),
                    ("vat", "VAT", 60, "center")]
        else:
            cols = ([("ldate", "Date", 90, "w")] if mode == "sale" else []) + \
                   [("desc", "Description", 220, "w"), ("acct", "Account", 200, "w"), ("qty", "Qty", 60, "e"),
                    ("price", "Unit price", 100, "e"), ("disc", "Disc", 60, "e"), ("vat", "VAT", 60, "center"),
                    ("amt", "Amount", 110, "e")]
        if self.show_depts:
            cols.append(("dept", "Department", 110, "w"))
        self.table = Table(self, cols, height=5)
        self.table.pack(fill="both", expand=True)
        bar = ttk.Frame(self, style="Card.TFrame")
        bar.pack(fill="x", pady=(6, 0))
        ttk.Button(bar, text="Remove selected line", command=self.remove_line).pack(side="left")
        self.total_lbl = ttk.Label(bar, text="", style="Card.TLabel", font=f(11, "bold"))
        self.total_lbl.pack(side="right")
        self.on_change = None

    def _lookup(self, opts, label):
        return next((o[0] for o in opts if o[1] == label), None)

    def _label(self, opts, value):
        return next((o[1] for o in opts if o[0] == value), "")

    def _item_chosen(self, _e=None):
        iid = self._lookup(self.item_opts, self.v["item"].get())
        it = self.items_by_id.get(iid)
        if not it:
            return
        self.v["desc"].set(it["name"])
        self.v["price"].set(f"{(it['sale_price'] if self.mode == 'sale' else it['cost_price']):g}")
        acc = it["income_account_id"] if self.mode == "sale" else it["expense_account_id"]
        if acc and self.mode == "sale":
            self.v["acct"].set(self._label(self.acct_opts, acc))
        self.v["vat"].set(self.vat_opts[0] if it["vatable"] else "0%")

    def add_line(self):
        try:
            item_id = self._lookup(self.item_opts, self.v["item"].get()) if self.item_opts else None
            acct = self._lookup(self.acct_opts, self.v["acct"].get())
            dept = self._lookup(self.dept_opts, self.v["dept"].get()) if self.show_depts else None
            rate = float(self.v["vat"].get().rstrip("%") or 0)
            line = {"item_id": item_id, "account_id": acct, "department_id": dept,
                    "description": self.v["desc"].get().strip()}
            if self.mode == "journal":
                dr, cr = num(self.v["dr"].get()), num(self.v["cr"].get())
                if not acct or (dr and cr) or not (dr or cr):
                    raise ValueError("Choose an account and enter either a debit or a credit.")
                line.update(debit=dr, credit=cr)
            elif self.mode == "expense":
                amt = num(self.v["price"].get())
                if not acct or amt <= 0:
                    raise ValueError("Choose an account and enter an amount.")
                line.update(amount=amt, vat_rate=rate)
            else:
                if not acct and not item_id:
                    raise ValueError("Choose an item or an account.")
                qty, price = num(self.v["qty"].get(), 1), num(self.v["price"].get())
                disc = num(self.v["disc"].get().rstrip("%"), 0)
                if qty <= 0:
                    raise ValueError("Quantity must be greater than zero.")
                if not 0 <= disc <= 100:
                    raise ValueError("Discount must be between 0 and 100 percent.")
                line.update(qty=qty, unit_price=price, vat_rate=rate, discount_pct=disc,
                            line_date=self.v["ldate"].get().strip())
        except ValueError as exc:
            error(self, exc)
            return
        self.lines.append(line)
        for k in ("item", "desc", "price", "dr", "cr", "disc"):
            self.v[k].set("")
        self.v["qty"].set("1")
        self.refresh()

    def remove_line(self):
        sel = self.table.selected()
        if sel is not None:
            del self.lines[int(sel)]
            self.refresh()

    def refresh(self):
        rows = []
        for l in self.lines:
            acct = self._label(self.acct_opts, l.get("account_id")) or "(item default)"
            dept = self._label(self.dept_opts, l.get("department_id"))
            if self.mode == "journal":
                r = [acct, l["description"], money(l["debit"], True), money(l["credit"], True)]
            elif self.mode == "expense":
                r = [acct, l["description"], money(l["amount"]), f"{l['vat_rate']:g}%"]
            else:
                d = l.get("discount_pct") or 0
                r = ([l.get("line_date", "")] if self.mode == "sale" else []) + \
                    [l["description"], acct, f"{l['qty']:g}", money(l["unit_price"]), f"{d:g}%" if d else "",
                     f"{l['vat_rate']:g}%", money(l["qty"] * l["unit_price"] * (1 - d / 100))]
            if self.show_depts:
                r.append(dept)
            rows.append(r)
        self.table.set_rows(rows, ids=list(range(len(rows))))
        if self.mode == "journal":
            dr = sum(l["debit"] for l in self.lines)
            cr = sum(l["credit"] for l in self.lines)
            self.total_lbl.configure(text=f"Debits {money(dr)}   Credits {money(cr)}   Difference {money(dr - cr)}",
                                     foreground=C.EMERALD if abs(dr - cr) < 0.005 else C.DANGER)
        elif self.mode == "expense":
            self.total_lbl.configure(text=f"Total  MWK {money(sum(l['amount'] for l in self.lines))}")
        if self.on_change:
            self.on_change()


class BarChart(tk.Canvas):
    def __init__(self, parent, height=200, **kw):
        super().__init__(parent, height=height, bg=C.CARD, highlightthickness=0, **kw)
        self.data = []
        self.bind("<Configure>", lambda e: self.draw())

    def set_data(self, data):
        """data: [(label, income, expense)]"""
        self.data = data
        self.draw()

    def draw(self):
        self.delete("all")
        if not self.data:
            return
        w, h = self.winfo_width() or 500, self.winfo_height() or 200
        pad_l, pad_b, pad_t = 60, 26, 24
        mx = max([max(i, e) for _, i, e in self.data] + [1])
        n = len(self.data)
        gw = (w - pad_l - 10) / n
        bw = min(22, gw / 3)
        for k in range(5):
            y = pad_t + (h - pad_t - pad_b) * k / 4
            self.create_line(pad_l, y, w - 10, y, fill="#EEF2F6")
            v = mx * (1 - k / 4)
            lab = f"{v / 1e6:.1f}M" if mx >= 1e6 else f"{v / 1e3:.0f}K"
            self.create_text(pad_l - 8, y, text=lab, anchor="e", fill=C.MUTED, font=f(8))
        for i, (label, inc, exp) in enumerate(self.data):
            cx = pad_l + gw * i + gw / 2
            for j, (val, col) in enumerate(((inc, C.EMERALD), (exp, C.NAVY_3))):
                x0 = cx - bw - 2 + j * (bw + 4)
                y1 = h - pad_b
                y0 = y1 - (h - pad_t - pad_b) * (val / mx)
                self.create_rectangle(x0, y0, x0 + bw, y1, fill=col, outline="")
            self.create_text(cx, h - pad_b + 12, text=label, fill=C.MUTED, font=f(9))
        self.create_rectangle(pad_l, 6, pad_l + 10, 16, fill=C.EMERALD, outline="")
        self.create_text(pad_l + 14, 11, text="Income", anchor="w", fill=C.TEXT, font=f(8))
        self.create_rectangle(pad_l + 70, 6, pad_l + 80, 16, fill=C.NAVY_3, outline="")
        self.create_text(pad_l + 84, 11, text="Expenses", anchor="w", fill=C.TEXT, font=f(8))
