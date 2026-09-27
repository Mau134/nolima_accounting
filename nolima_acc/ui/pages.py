"""Pages shown in the main window."""
import tkinter as tk
from datetime import date, timedelta
from pathlib import Path
from tkinter import filedialog, ttk

from .. import config as C, licensing, plans, printing
from ..services import ROLES, AccError, InUse, export_csv
from .dialogs import (ExpenseDialog, InvoiceDialog, JournalDialog, PaymentDialog, ReconcileDialog,
                      contact_form)
from .theme import f, money
from .widgets import BarChart, Card, ColorTabs, FormDialog, Table, confirm, error, info, valid_date


class Page(ttk.Frame):
    title = ""

    def __init__(self, parent, app):
        super().__init__(parent, padding=(26, 20))
        self.app, self.books = app, app.books
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 14))
        ttk.Label(top, text=self.title, style="H1.TLabel").pack(side="left")
        self.actions = ttk.Frame(top)
        self.actions.pack(side="right")

    def action(self, text, cmd, primary=False):
        b = ttk.Button(self.actions, text=text, command=self._safe(cmd), style="Primary.TButton" if primary else "TButton")
        b.pack(side="left", padx=4)
        return b

    def _safe(self, fn):
        def run(*a):
            try:
                return fn(*a)
            except AccError as exc:
                error(self, exc)
        return run

    def refresh(self):
        pass

    def delete_or_hide(self, name, delete_fn, table, rid):
        """Delete a record; if it has history, offer to hide it instead."""
        if not confirm(self, f"Delete {name}? This cannot be undone."):
            return False
        try:
            delete_fn(rid)
            info(self, f"{name} deleted.")
            return True
        except InUse as exc:
            if confirm(self, f"{exc}\n\nHide {name} now?", "Cannot delete"):
                self.books.set_active(table, rid, False)
                info(self, f"{name} is hidden. Tick 'Show hidden' to see it again.")
                return True
        return False


LIST_LIMIT = 500  # rows shown per list; searching reaches older records


def search_bar(parent, on_change, extra=None):
    bar = ttk.Frame(parent, style="Card.TFrame")
    bar.pack(fill="x", pady=(0, 8))
    v = tk.StringVar()
    ttk.Label(bar, text="Search", style="CardMuted.TLabel").pack(side="left")
    e = ttk.Entry(bar, textvariable=v, width=22)
    e.pack(side="left", padx=8)
    job = {"id": None}

    def later(_ev=None):  # wait until typing pauses instead of reloading on every key
        if job["id"]:
            bar.after_cancel(job["id"])
        job["id"] = bar.after(300, on_change)
    e.bind("<KeyRelease>", later)
    if extra:
        extra(bar)
    return v, bar


# ====================================================================== dashboard
class DashboardPage(ttk.Frame):
    """Glassmorphism dashboard: frosted panels over a blurred colour backdrop, drawn on one canvas."""
    title = "Dashboard"
    TEXT, MUTED, FAINT = "#FFFFFF", "#B9C8DA", "#4B6784"
    KPIS = [("income_month", "Income", "up", ("#34D399", "#059669")),
            ("expense_month", "Expenses", "down", ("#FB7185", "#BE123C")),
            ("profit_month", "Profit", "trend", ("#A78BFA", "#6D28D9")),
            ("cash", "Cash & bank", "wallet", ("#22D3EE", "#0E7490")),
            ("receivables", "Receivables", "in", ("#60A5FA", "#1D4ED8")),
            ("payables", "Payables", "out", ("#FBBF24", "#B45309"))]

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.books = app, app.books
        self.cv = tk.Canvas(self, highlightthickness=0, bd=0, bg="#0B2340")
        self.cv.pack(fill="both", expand=True)
        self.data = None
        self._job = None
        self._size = (0, 0)
        self._bg = None
        self.cv.bind("<Configure>", lambda e: self._schedule())
        from . import art
        self.art = art
        self.badges = {k: art.badge(k, 40, cols, glyph) for k, _, glyph, cols in self.KPIS}

    def refresh(self):
        self.data = self.books.dashboard()
        self._schedule()

    def _schedule(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(90, self.render)

    # layout -----------------------------------------------------------------
    def _layout(self, W, H):
        pad, gap = 28, 16
        L = {"pad": pad}
        ky = 96
        kh = 118
        cols = 3 if W < 1060 else 6
        rows = 6 // cols
        kw = (W - 2 * pad - gap * (cols - 1)) / cols
        L["kpis"] = [(pad + (i % cols) * (kw + gap), ky + (i // cols) * (kh + gap),
                      pad + (i % cols) * (kw + gap) + kw, ky + (i // cols) * (kh + gap) + kh) for i in range(6)]
        my = ky + rows * (kh + gap)
        rest = H - my - pad
        mh = max(220, rest * 0.56)
        cw = (W - 2 * pad - gap) * 0.64
        L["chart"] = (pad, my, pad + cw, my + mh)
        L["banks"] = (pad + cw + gap, my, W - pad, my + mh)
        L["recent"] = (pad, my + mh + gap, W - pad, max(my + mh + gap + 120, H - pad))
        return L

    def render(self):
        self._job = None
        if self.data is None:
            return
        W, H = self.cv.winfo_width(), self.cv.winfo_height()
        if W < 50 or H < 50:
            return
        L = self._layout(W, H)
        boxes = L["kpis"] + [L["chart"], L["banks"], L["recent"]]
        if self._size != (W, H):
            img = self.art.compose_glass(W, H, tuple(tuple(int(v) for v in b) for b in boxes))
            self._bg = self.art.ImageTk.PhotoImage(img)
            self._size = (W, H)
        cv, d = self.cv, self.data
        cv.delete("all")
        cv.create_image(0, 0, image=self._bg, anchor="nw")
        pad = L["pad"]
        cv.create_text(pad, 34, text="Dashboard", anchor="w", fill=self.TEXT, font=f(21, "bold"))
        co = self.books.setting("company_name", "")
        cv.create_text(pad, 64, text=f"{co}  \u00b7  {date.today():%A, %d %B %Y}", anchor="w", fill=self.MUTED,
                       font=f(10))
        x = W - pad
        if self.books.can("post"):
            x = self._button(x, 32, "Cash sale", lambda: self.app.open_dialog(InvoiceDialog, "sale", True), False)
            x = self._button(x - 10, 32, "+  New invoice", lambda: self.app.open_dialog(InvoiceDialog, "sale"), True)
        # KPI cards
        for (key, label, _g, _c), (x0, y0, x1, y1) in zip(self.KPIS, L["kpis"]):
            cv.create_image(x0 + 18, y0 + 18, image=self.badges[key], anchor="nw")
            cv.create_text(x0 + 70, y0 + 38, text=label, anchor="w", fill=self.MUTED, font=f(9, "bold"),
                           width=x1 - x0 - 84)
            v = d[key]
            txt = f"({abs(v):,.0f})" if v < 0 else f"{v:,.0f}"
            cv.create_text(x0 + 18, y0 + 80, text=txt, anchor="w",
                           fill="#FDA4AF" if v < 0 else self.TEXT, font=f(15, "bold"))
            sub = {"receivables": f"MWK \u00b7 {d['overdue']} overdue", "cash": "MWK \u00b7 all accounts",
                   "expense_month": f"MWK \u00b7 {d['paid_out_month']:,.0f} paid out",
                   "payables": "MWK \u00b7 unpaid bills"}.get(key, "MWK \u00b7 this month")
            cv.create_text(x0 + 18, y0 + 102, text=sub, anchor="w", fill=self.MUTED, font=f(8))
        self._chart(L["chart"])
        self._banks(L["banks"])
        self._recent(L["recent"])

    def _button(self, right, cy, text, cmd, primary):
        import tkinter.font as tkfont
        w = tkfont.Font(font=f(10, "bold")).measure(text) + 40
        key = ("btn", text, primary)
        if not hasattr(self, "_btns"):
            self._btns = {}
        if key not in self._btns:
            if primary:
                self._btns[key] = (self.art.pill(w, 40, "#10B981"), self.art.pill(w, 40, "#34D399"))
            else:
                self._btns[key] = (self.art.pill(w, 40, (255, 255, 255, 40), (255, 255, 255, 120)),
                                   self.art.pill(w, 40, (255, 255, 255, 70), (255, 255, 255, 160)))
        normal, hover = self._btns[key]
        tag = f"btn{abs(hash(text))}"
        img = self.cv.create_image(right, cy, image=normal, anchor="e", tags=tag)
        self.cv.create_text(right - w / 2, cy, text=text, fill="white", font=f(10, "bold"), tags=tag)
        self.cv.tag_bind(tag, "<Button-1>", lambda e: cmd())
        self.cv.tag_bind(tag, "<Enter>", lambda e: (self.cv.itemconfigure(img, image=hover),
                                                    self.cv.configure(cursor="hand2")))
        self.cv.tag_bind(tag, "<Leave>", lambda e: (self.cv.itemconfigure(img, image=normal),
                                                    self.cv.configure(cursor="")))
        return right - w

    def _title(self, box, text):
        self.cv.create_text(box[0] + 22, box[1] + 28, text=text, anchor="w", fill=self.TEXT, font=f(12, "bold"))

    def _chart(self, box):
        cv = self.cv
        x0, y0, x1, y1 = box
        self._title(box, "Income vs expenses \u00b7 last 6 months")
        months = self.data["months"]
        mx = max([max(m["income"], m["expense"]) for m in months] + [1])
        L, R, T, B = x0 + 70, x1 - 24, y0 + 70, y1 - 40
        for i, col, lab in ((0, "#34D399", "Income"), (1, "#FDA4AF", "Expenses")):
            lx = x1 - 190 + i * 90
            cv.create_oval(lx, y0 + 23, lx + 10, y0 + 33, fill=col, outline="")
            cv.create_text(lx + 16, y0 + 28, text=lab, anchor="w", fill=self.MUTED, font=f(9))
        for k in range(5):
            y = T + (B - T) * k / 4
            cv.create_line(L, y, R, y, fill="#34506E", dash=(2, 4))
            v = mx * (1 - k / 4)
            cv.create_text(L - 10, y, text=f"{v / 1e6:.1f}M" if mx >= 1e6 else f"{v / 1e3:.0f}K", anchor="e",
                           fill=self.MUTED, font=f(8))
        gw = (R - L) / max(1, len(months))
        bw = min(26, gw / 3.2)
        for i, m in enumerate(months):
            cx = L + gw * i + gw / 2
            for j, (val, col) in enumerate(((m["income"], "#34D399"), (m["expense"], "#FDA4AF"))):
                bx = cx - bw - 3 + j * (bw + 6)
                top = B - (B - T) * (val / mx)
                self._rbar(bx, top, bx + bw, B, col)
            cv.create_text(cx, B + 18, text=m["label"], fill=self.MUTED, font=f(9))

    def _rbar(self, x0, y0, x1, y1, col):
        r = min(6, (x1 - x0) / 2, max(0, (y1 - y0)) / 2)
        cv = self.cv
        if y1 - y0 < 1:
            return
        cv.create_rectangle(x0, y0 + r, x1, y1, fill=col, outline="")
        cv.create_rectangle(x0 + r, y0, x1 - r, y0 + r, fill=col, outline="")
        cv.create_oval(x0, y0, x0 + 2 * r, y0 + 2 * r, fill=col, outline="")
        cv.create_oval(x1 - 2 * r, y0, x1, y0 + 2 * r, fill=col, outline="")

    def _banks(self, box):
        cv = self.cv
        x0, y0, x1, y1 = box
        self._title(box, "Cash, bank and mobile money")
        y = y0 + 66
        total = 0
        for b in self.data["banks"]:
            if y > y1 - 70:
                break
            cv.create_text(x0 + 22, y, text=b["name"], anchor="w", fill=self.TEXT, font=f(10), width=x1 - x0 - 170)
            cv.create_text(x1 - 22, y, text=money(b["balance"]), anchor="e", fill=self.TEXT, font=f(10, "bold"))
            cv.create_line(x0 + 22, y + 20, x1 - 22, y + 20, fill="#34506E")
            total += b["balance"]
            y += 42
        cv.create_text(x0 + 22, y1 - 34, text="Total available", anchor="w", fill=self.MUTED, font=f(10))
        cv.create_text(x1 - 22, y1 - 34, text=f"MWK {money(total)}", anchor="e", fill="#6EE7B7", font=f(13, "bold"))

    def _recent(self, box):
        cv = self.cv
        x0, y0, x1, y1 = box
        self._title(box, "Recent transactions")
        cols = [(x0 + 22, "DATE", "w"), (x0 + 140, "REFERENCE", "w"), (x0 + 280, "DETAILS", "w"),
                (x1 - 22, "AMOUNT (MWK)", "e")]
        hy = y0 + 60
        for x, t, a in cols:
            cv.create_text(x, hy, text=t, anchor=a, fill=self.MUTED, font=f(8, "bold"))
        y = hy + 28
        for r in self.data["recent"]:
            if y > y1 - 16:
                break
            cv.create_text(cols[0][0], y, text=r["date"], anchor="w", fill=self.MUTED, font=f(10))
            cv.create_text(cols[1][0], y, text=r["ref"] or "", anchor="w", fill=self.TEXT, font=f(10, "bold"))
            cv.create_text(cols[2][0], y, text=r["memo"], anchor="w", fill=self.TEXT, font=f(10),
                           width=x1 - x0 - 460)
            cv.create_text(cols[3][0], y, text=money(r["amount"]), anchor="e", fill=self.TEXT, font=f(10))
            y += 32


# ====================================================================== sales / purchases
class DocumentsPage(Page):
    """Shared layout for Sales (kind='sale') and Purchases (kind='bill')."""
    kind = "sale"

    def __init__(self, parent, app):
        super().__init__(parent, app)
        sale = self.kind == "sale"
        self.ckind = "customer" if sale else "supplier"
        self.pkind = "receipt" if sale else "payment"
        if self.books.can("post"):
            if sale:
                self.action("Cash sale", lambda: self.app.open_dialog(InvoiceDialog, "sale", True))
            self.action("Receive payment" if sale else "Pay supplier",
                        lambda: self.app.open_dialog(PaymentDialog, self.pkind))
            if sale:
                self.action("New quotation", lambda: self.app.open_dialog(InvoiceDialog, "quote"))
            self.action("New invoice" if sale else "New bill", lambda: self.app.open_dialog(InvoiceDialog, self.kind), True)
        nb = ColorTabs(self)
        nb.pack(fill="both", expand=True)
        # documents tab
        t1 = Card(nb)
        nb.add(t1, text="Invoices" if sale else "Bills")
        self.status = tk.StringVar(value="All")

        def extra(bar):
            ttk.Label(bar, text="Show", style="CardMuted.TLabel").pack(side="left", padx=(12, 4))
            cb = ttk.Combobox(bar, textvariable=self.status, values=["All", "Unpaid", "Part paid", "Paid", "Void"],
                              width=10, state="readonly")
            cb.pack(side="left")
            cb.bind("<<ComboboxSelected>>", lambda e: self.refresh_docs())
            actions = [("Print", self.print_doc), ("Record payment", self.pay_doc), ("View entry", self.view_entry),
                       ("Void", self.void_doc)]
            if sale:
                actions.insert(2, ("Withholding tax", self.add_wht))
            for text, cmd in actions:
                ttk.Button(bar, text=text, command=self._safe(cmd)).pack(side="right", padx=3)
        self.search, _ = search_bar(t1, self.refresh_docs, extra)
        self.docs = Table(t1, [("num", "Number", 110, "w"), ("date", "Date", 95, "w"), ("due", "Due", 95, "w"),
                               ("c", "Customer" if sale else "Supplier", 240, "w"), ("ref", "Reference", 120, "w"),
                               ("tot", "Total", 120, "e"), ("bal", "Balance", 120, "e"), ("st", "Status", 80, "center")],
                          on_double=lambda i: self.print_doc(), money_cols=["tot", "bal"])
        self.docs.pack(fill="both", expand=True)
        # payments tab
        t2 = Card(nb)
        nb.add(t2, text="Receipts" if sale else "Payments")

        def extra2(bar):
            ttk.Button(bar, text="Void", command=self._safe(self.void_payment)).pack(side="right", padx=3)
            ttk.Button(bar, text="Print", command=self._safe(self.print_payment)).pack(side="right", padx=3)
        self.psearch, _ = search_bar(t2, self.refresh_pays, extra2)
        self.pays = Table(t2, [("num", "Number", 110, "w"), ("date", "Date", 95, "w"), ("c", "Name", 240, "w"),
                               ("acc", "Account", 200, "w"), ("m", "Method", 110, "w"), ("ref", "Reference", 120, "w"),
                               ("amt", "Amount", 120, "e"), ("st", "Status", 80, "center")], money_cols=["amt"])
        self.pays.pack(fill="both", expand=True)
        # contacts tab
        t3 = Card(nb)
        nb.add(t3, text="Customers" if sale else "Suppliers")

        def extra3(bar):
            ttk.Button(bar, text="Statement", command=self._safe(self.statement)).pack(side="right", padx=3)
            ttk.Button(bar, text="Delete", style="Danger.TButton",
                       command=self._safe(self.delete_contact)).pack(side="right", padx=3)
            ttk.Button(bar, text="Edit", command=self._safe(self.edit_contact)).pack(side="right", padx=3)
            ttk.Checkbutton(bar, text="Show hidden", variable=self.show_hidden, style="Card.TCheckbutton",
                            command=self.refresh_contacts).pack(side="left", padx=10)
            ttk.Button(bar, text=f"New {self.ckind}", style="Primary.TButton",
                       command=self._safe(self.new_contact)).pack(side="right", padx=3)
        self.show_hidden = tk.BooleanVar(value=False)
        self.csearch, _ = search_bar(t3, self.refresh_contacts, extra3)
        self.cons = Table(t3, [("n", "Name", 260, "w"), ("p", "Phone", 140, "w"), ("e", "Email", 220, "w"),
                               ("t", "TPIN", 110, "w"), ("b", "Balance", 130, "e")],
                          on_double=lambda i: self.edit_contact(), money_cols=["b"])
        self.cons.pack(fill="both", expand=True)
        self.quotes = None
        if sale:
            t4 = Card(nb)
            nb.add(t4, text="Quotations")

            def extra4(bar):
                for text, cmd in [("Delete", self.delete_quote), ("Cancel", lambda: self.quote_status("cancelled")),
                                  ("Declined", lambda: self.quote_status("declined")),
                                  ("Accepted", lambda: self.quote_status("accepted")),
                                  ("Print", self.print_quote), ("Convert to invoice", self.convert_quote)]:
                    ttk.Button(bar, text=text, command=self._safe(cmd),
                               style="Primary.TButton" if text.startswith("Convert") else "TButton"
                               ).pack(side="right", padx=3)
            self.qsearch, _ = search_bar(t4, self.refresh_quotes, extra4)
            self.quotes = Table(t4, [("num", "Number", 110, "w"), ("date", "Date", 95, "w"),
                                     ("valid", "Valid until", 95, "w"), ("c", "Customer", 240, "w"),
                                     ("ref", "Reference", 120, "w"), ("tot", "Total", 120, "e"),
                                     ("st", "Status", 90, "center")],
                                on_double=lambda i: self.print_quote(), money_cols=["tot"])
            self.quotes.pack(fill="both", expand=True)
        self.tabs = nb
        nb.bind("<<TabChanged>>", lambda e: self.refresh())

    def refresh(self):
        # only the visible tab is reloaded: fewer queries, faster page
        i = self.tabs.index or 0
        [self.refresh_docs, self.refresh_pays, self.refresh_contacts, self.refresh_quotes][i]()

    def refresh_quotes(self):
        if not self.quotes:
            return
        today = date.today().isoformat()
        rows = self.books.quotes(search=self.qsearch.get(), limit=LIST_LIMIT)
        self.quotes.set_rows([[q["number"], q["date"], q["valid_until"], q["contact"], q["reference"], q["total"],
                               ("Expired" if q["status"] == "open" and (q["valid_until"] or "") < today
                                else q["status"].title())] for q in rows],
                             ids=[q["id"] for q in rows],
                             tags=[("muted",) if q["status"] in ("invoiced", "cancelled", "declined") else ()
                                   for q in rows])

    def _quote(self):
        i = self.quotes.selected()
        if not i:
            raise AccError("Select a quotation first.")
        return int(i)

    def print_quote(self):
        printing.print_quote(self.books, self._quote())

    def delete_quote(self):
        q = self.books.quote(self._quote())
        if confirm(self, f"Delete quotation {q['number']}? This cannot be undone."):
            self.books.delete_quote(q["id"])
            self.refresh_quotes()

    def quote_status(self, status):
        self.books.set_quote_status(self._quote(), status)
        self.refresh_quotes()

    def convert_quote(self):
        q = self.books.quote(self._quote())
        if confirm(self, f"Create an invoice from quotation {q['number']} for MWK {money(q['total'])}?"):
            inv = self.books.convert_quote(q["id"])
            self.refresh_quotes()
            if confirm(self, "Invoice created. Print it now?"):
                printing.print_invoice(self.books, inv)

    def refresh_docs(self):
        st = {"All": None, "Unpaid": "unpaid", "Part paid": "partial", "Paid": "paid",
              "Void": "void"}[self.status.get()]
        rows = self.books.invoices(self.kind, st, search=self.search.get(), limit=LIST_LIMIT)
        today = date.today().isoformat()
        tags = [("red",) if r["status"] in ("open", "partial") and (r["due_date"] or "") < today
                else ("muted",) if r["status"] == "void" else () for r in rows]
        self.docs.set_rows([[r["number"], r["date"], r["due_date"], r["contact"], r["reference"], r["total"],
                             r["balance"] if r["status"] != "void" else 0,
                             "Part paid" if r["status"] == "partial" else r["status"].title()] for r in rows],
                           ids=[r["id"] for r in rows], tags=tags)

    def refresh_pays(self):
        ps = self.books.payments(self.pkind, search=self.psearch.get(), limit=LIST_LIMIT)
        self.pays.set_rows([[p["number"], p["date"], p["contact"], p["account"], p["method"], p["reference"],
                             p["amount"], p["status"].title()] for p in ps], ids=[p["id"] for p in ps],
                           tags=[("muted",) if p["status"] == "void" else () for p in ps])

    def refresh_contacts(self):
        cs = self.books.contacts(self.ckind, active_only=not self.show_hidden.get(), search=self.csearch.get())
        bal = self.books.contact_balances(self.ckind)
        self.cons.set_rows([[c["name"] + ("" if c["active"] else "  (hidden)"), c["phone"], c["email"], c["tpin"],
                             bal.get(c["id"], 0.0)] for c in cs], ids=[c["id"] for c in cs],
                           tags=[() if c["active"] else ("muted",) for c in cs])

    def _doc(self):
        i = self.docs.selected()
        if not i:
            raise AccError("Select a document first.")
        return int(i)

    def print_doc(self):
        printing.print_invoice(self.books, self._doc())

    def pay_doc(self):
        inv = self.books.invoice(self._doc())
        self.app.open_dialog(PaymentDialog, self.pkind, inv["contact_id"], inv["id"])

    def add_wht(self):
        inv = self.books.invoice(self._doc())
        bal = inv["total"] - inv["amount_paid"]
        v = FormDialog(self, f"Withholding tax on {inv['number']}", [
            ("amount", f"Withholding tax deducted by {inv['contact']} (MWK)", "number"),
            ("date", "Date", "date")],
            lambda v: self.books.add_invoice_wht(inv["id"], v["amount"], v["date"]),
            ok_text="Record withholding tax").show()
        if v:
            self.app.refresh()
            info(self, f"Withholding tax recorded. Balance still due on {inv['number']}: "
                       f"MWK {money(bal - v['amount'])}. Keep the customer's WHT certificate.")

    def view_entry(self):
        inv = self.books.invoice(self._doc())
        self.app.show_entry(inv["entry_id"])

    def void_doc(self):
        inv = self.books.invoice(self._doc())
        if confirm(self, f"Void {inv['number']}? A reversing entry will be posted."):
            self.books.void_invoice(inv["id"], "Voided by user")
            self.app.refresh()

    def _pay(self):
        i = self.pays.selected()
        if not i:
            raise AccError("Select a payment first.")
        return int(i)

    def print_payment(self):
        printing.print_payment(self.books, self._pay())

    def void_payment(self):
        pid = self._pay()
        if confirm(self, "Void this payment? Its allocations will be removed."):
            self.books.void_payment(pid, "Voided by user")
            self.app.refresh()

    def new_contact(self):
        if contact_form(self, self.books, self.ckind):
            self.refresh()

    def edit_contact(self):
        i = self.cons.selected()
        if not i:
            raise AccError("Select a contact first.")
        c = dict(self.books.one("SELECT * FROM contacts WHERE id=?", (int(i),)))
        if contact_form(self, self.books, self.ckind, c):
            self.refresh()

    def delete_contact(self):
        i = self.cons.selected()
        if not i:
            raise AccError("Select a contact first.")
        c = self.books.one("SELECT * FROM contacts WHERE id=?", (int(i),))
        if self.delete_or_hide(c["name"], self.books.delete_contact, "contacts", c["id"]):
            self.refresh_contacts()

    def statement(self):
        i = self.cons.selected()
        if not i:
            raise AccError("Select a contact first.")
        self.app.show_page("Reports")
        self.app.pages["Reports"].run_report("Customer / supplier statement", contact_id=int(i))


class SalesPage(DocumentsPage):
    title, kind = "Sales", "sale"


class PurchasesPage(DocumentsPage):
    title, kind = "Purchases", "bill"


# ====================================================================== banking
class BankingPage(Page):
    title = "Banking"

    def __init__(self, parent, app):
        super().__init__(parent, app)
        if self.books.can("post"):
            self.action("Transfer", self.transfer)
            self.action("Receive money", self.receive)
            self.action("Spend money", lambda: self.app.open_dialog(ExpenseDialog), True)
        c = Card(self, "Accounts")
        c.pack(fill="both", expand=True)
        bar = ttk.Frame(c, style="Card.TFrame")
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="Cash book", command=self._safe(self.cash_book)).pack(side="left")
        self.rec_btn = ttk.Button(bar, text="Reconcile", command=self._safe(self.reconcile))
        self.rec_btn.pack(side="left", padx=6)
        ttk.Button(bar, text="Add bank / mobile money account", command=self._safe(self.add_account)).pack(side="right")
        self.table = Table(c, [("c", "Code", 80, "w"), ("n", "Account", 320, "w"), ("t", "Type", 110, "w"),
                               ("r", "Last reconciled", 140, "w"), ("b", "Balance", 140, "e")],
                           on_double=lambda i: self.cash_book(), money_cols=["b"])
        self.table.pack(fill="both", expand=True)

    def refresh(self):
        accs = self.books.bank_accounts()
        rows = []
        for a in accs:
            last = self.books.val("SELECT MAX(statement_date) FROM reconciliations WHERE account_id=?", (a["id"],), "")
            rows.append([a["code"], a["name"], a["subtype"].title(), last, self.books.balance(a["id"])])
        self.table.set_rows(rows, ids=[a["id"] for a in accs])
        self.rec_btn.state(["!disabled"] if self.books.has_module("bank_rec") else ["disabled"])

    def _acc(self):
        i = self.table.selected()
        if not i:
            raise AccError("Select an account first.")
        return int(i)

    def cash_book(self):
        self.app.show_page("Reports")
        self.app.pages["Reports"].run_report("General ledger / cash book", account_id=self._acc())

    def reconcile(self):
        self.books.need_module("bank_rec")
        self.app.open_dialog(ReconcileDialog, self._acc())

    def add_account(self):
        v = FormDialog(self, "New bank or mobile money account",
                       [("code", "Code (e.g. 1030)", "entry"), ("name", "Name", "entry"),
                        ("sub", "Type", "combo", [("bank", "Bank or mobile money"), ("cash", "Cash")])]).show()
        if v:
            self.books.save_account(v["code"], v["name"], "asset", v["sub"])
            self.refresh()

    def transfer(self):
        banks = [(a["id"], a["name"]) for a in self.books.bank_accounts()]
        v = FormDialog(self, "Transfer between accounts",
                       [("date", "Date", "date"), ("from", "From", "combo", banks),
                        ("to", "To", "combo", banks, banks[1][0] if len(banks) > 1 else None),
                        ("amount", "Amount", "number"), ("memo", "Details", "entry", None, "Transfer"),
                        ("ref", "Reference", "entry")],
                       lambda v: self.books.transfer(v["date"], v["from"], v["to"], v["amount"], v["memo"], v["ref"])).show()
        if v:
            self.app.refresh()

    def receive(self):
        banks = [(a["id"], a["name"]) for a in self.books.bank_accounts()]
        inc = [(a["id"], f"{a['code']}  {a['name']}") for a in self.books.accounts(types=["income", "liability", "equity"])]
        v = FormDialog(self, "Receive money (not from an invoice)",
                       [("date", "Date", "date"), ("bank", "Into", "combo", banks), ("acc", "Account", "combo", inc),
                        ("amount", "Amount", "number"), ("payer", "Received from", "entry"),
                        ("memo", "Details", "entry"), ("ref", "Reference", "entry")],
                       lambda v: self.books.record_other_receipt(v["date"], v["bank"], v["acc"], v["amount"],
                                                                 v["payer"], v["ref"], v["memo"])).show()
        if v:
            self.app.refresh()


# ====================================================================== items
class ItemsPage(Page):
    title = "Items and inventory"

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.action("Delete", self.delete)
        self.action("Stock adjustment", self.adjust)
        self.action("Edit item", self.edit)
        self.action("New item", self.new, True)
        c = Card(self)
        c.pack(fill="both", expand=True)
        self.show_hidden = tk.BooleanVar(value=False)
        self.search, _ = search_bar(c, self.refresh, lambda bar: ttk.Checkbutton(
            bar, text="Show hidden", variable=self.show_hidden, style="Card.TCheckbutton",
            command=self.refresh).pack(side="left", padx=10))
        self.table = Table(c, [("c", "Code", 90, "w"), ("n", "Name", 260, "w"), ("k", "Type", 80, "w"),
                               ("u", "Unit", 70, "w"), ("sp", "Sale price", 110, "e"), ("cp", "Avg cost", 110, "e"),
                               ("q", "On hand", 90, "e"), ("v", "Stock value", 120, "e")],
                           on_double=lambda i: self.edit(), money_cols=["sp", "cp", "v"])
        self.table.pack(fill="both", expand=True)

    def refresh(self):
        its = self.books.items(active_only=not self.show_hidden.get(), search=self.search.get())
        self.table.set_rows([[i["code"], i["name"] + ("" if i["active"] else "  (hidden)"), i["kind"].title(), i["unit"], i["sale_price"], i["cost_price"],
                              f"{i['qty_on_hand']:g}" if i["kind"] == "stock" else "",
                              i["qty_on_hand"] * i["cost_price"] if i["kind"] == "stock" else ""] for i in its],
                            ids=[i["id"] for i in its],
                            tags=[("red",) if i["kind"] == "stock" and i["qty_on_hand"] <= i["reorder_level"] else ()
                                  for i in its])

    def _form(self, it=None):
        it = it or {}
        inc = [(a["id"], f"{a['code']}  {a['name']}") for a in self.books.accounts(types=["income"])]
        exp = [(a["id"], f"{a['code']}  {a['name']}") for a in self.books.accounts(types=["expense"])]
        kinds = [("service", "Service (no stock)")]
        if self.books.has_module("inventory"):
            kinds.append(("stock", "Stock item (track quantity)"))
        v = FormDialog(self, "Item", [
            ("name", "Name", "entry", None, it.get("name")),
            ("code", "Code", "readonly", None, it.get("code") or "Automatic (STK-/SRV- number)"),
            ("kind", "Type", "combo", kinds, it.get("kind")), ("unit", "Unit", "entry", None, it.get("unit", "each")),
            ("sale", "Sale price (excl. VAT)", "number", None, it.get("sale_price", 0)),
            ("cost", "Purchase cost", "number", None, it.get("cost_price", 0)),
            ("inc", "Income account", "combo", inc, it.get("income_account_id")),
            ("exp", "Cost / expense account", "combo", exp, it.get("expense_account_id")),
            ("vat", "Charge VAT", "check", None, it.get("vatable", 1)),
            ("reorder", "Reorder level", "number", None, it.get("reorder_level", 0)),
            ("active", "Active (untick to hide)", "check", None, it.get("active", 1))],
            lambda v: self.books.save_item(v["name"], v["kind"], v["code"], v["unit"], v["sale"], v["cost"], v["inc"],
                                           v["exp"], v["vat"], v["reorder"], item_id=it.get("id"),
                                           active=v["active"])).show()
        if v:
            self.refresh()

    def new(self):
        self._form()

    def edit(self):
        i = self.table.selected()
        if not i:
            raise AccError("Select an item first.")
        self._form(dict(self.books.one("SELECT * FROM items WHERE id=?", (int(i),))))

    def delete(self):
        i = self.table.selected()
        if not i:
            raise AccError("Select an item first.")
        it = self.books.one("SELECT * FROM items WHERE id=?", (int(i),))
        if self.delete_or_hide(it["name"], self.books.delete_item, "items", it["id"]):
            self.refresh()

    def adjust(self):
        i = self.table.selected()
        if not i:
            raise AccError("Select a stock item first.")
        it = self.books.one("SELECT * FROM items WHERE id=?", (int(i),))
        v = FormDialog(self, f"Stock adjustment: {it['name']}", [
            ("date", "Date", "date"), ("qty", "Quantity change (+ add, - remove)", "number"),
            ("cost", "Unit cost (for additions)", "number", None, it["cost_price"]),
            ("memo", "Reason", "entry", None, "Stock count adjustment")],
            lambda v: self.books.adjust_stock(it["id"], v["qty"], v["date"], v["memo"], v["cost"])).show()
        if v:
            self.refresh()


# ====================================================================== accounting
class AccountingPage(Page):
    title = "Accounting"

    def __init__(self, parent, app):
        super().__init__(parent, app)
        if self.books.can("journal"):
            self.action("New journal", lambda: self.app.open_dialog(JournalDialog), True)
        nb = ColorTabs(self)
        nb.pack(fill="both", expand=True)
        t1 = Card(nb)
        nb.add(t1, text="Chart of accounts")

        def extra(bar):
            for text, cmd in [("Opening balance", self.opening), ("Deactivate", self.deactivate),
                              ("Edit", self.edit_account), ("New account", self.new_account)]:
                ttk.Button(bar, text=text, command=self._safe(cmd),
                           style="Primary.TButton" if text == "New account" else "TButton").pack(side="right", padx=3)
        self.asearch, _ = search_bar(t1, self.refresh, extra)
        self.accts = Table(t1, [("c", "Code", 80, "w"), ("n", "Account", 320, "w"), ("t", "Type", 100, "w"),
                                ("s", "Subtype", 110, "w"), ("b", "Balance", 140, "e")],
                           on_double=lambda i: self.ledger(), money_cols=["b"])
        self.accts.pack(fill="both", expand=True)
        t2 = Card(nb)
        nb.add(t2, text="Journal entries")
        bar = ttk.Frame(t2, style="Card.TFrame")
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="View lines", command=self._safe(self.view)).pack(side="left")
        ttk.Button(bar, text="Reverse manual journal", command=self._safe(self.reverse)).pack(side="left", padx=6)
        self.jr = Table(t2, [("id", "#", 60, "e"), ("d", "Date", 100, "w"), ("r", "Ref", 110, "w"),
                             ("s", "Source", 100, "w"), ("m", "Narration", 380, "w"), ("a", "Amount", 130, "e"),
                             ("u", "By", 90, "w")], on_double=lambda i: self.view(), money_cols=["a"])
        self.jr.pack(fill="both", expand=True)
        self.t3 = Card(nb)
        nb.add(self.t3, text="Departments")
        bar = ttk.Frame(self.t3, style="Card.TFrame")
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="New department", style="Primary.TButton", command=self._safe(self.new_dept)).pack(side="left")
        ttk.Button(bar, text="Rename / deactivate", command=self._safe(self.edit_dept)).pack(side="left", padx=6)
        self.depts = Table(self.t3, [("n", "Department", 300, "w"), ("a", "Active", 80, "center")])
        self.depts.pack(fill="both", expand=True)

    def refresh(self):
        s = self.asearch.get().lower()
        accs = [a for a in self.books.accounts(active_only=False) if s in (a["code"] + a["name"]).lower()]
        bal = self.books.balances()
        self.accts.set_rows([[a["code"], a["name"], a["type"].title(), a["subtype"], bal.get(a["id"], 0.0)]
                             for a in accs], ids=[a["id"] for a in accs],
                            tags=[("muted",) if not a["active"] else () for a in accs])
        js = self.books.journals(limit=LIST_LIMIT)
        self.jr.set_rows([[j["id"], j["date"], j["ref"], j["source_type"], j["memo"], j["amount"], j["created_by"]]
                          for j in js], ids=[j["id"] for j in js])
        ds = self.books.departments(active_only=False)
        self.depts.set_rows([[d["name"], "Yes" if d["active"] else "No"] for d in ds], ids=[d["id"] for d in ds])

    def _acc(self):
        i = self.accts.selected()
        if not i:
            raise AccError("Select an account first.")
        return dict(self.books.one("SELECT * FROM accounts WHERE id=?", (int(i),)))

    def _acc_form(self, a=None):
        a = a or {}
        types = [(t, t.title()) for t in ("asset", "liability", "equity", "income", "expense")]
        subs = [(s, s) for s in ("other", "bank", "cash", "fixed_asset", "contra_asset")]
        if a.get("subtype") and a["subtype"] not in dict(subs):
            subs.append((a["subtype"], a["subtype"]))
        v = FormDialog(self, "Account", [
            ("code", "Code", "entry", None, a.get("code")), ("name", "Name", "entry", None, a.get("name")),
            ("type", "Type", "combo", types, a.get("type")), ("sub", "Subtype", "combo", subs, a.get("subtype", "other")),
            ("desc", "Description", "entry", None, a.get("description"))],
            lambda v: self.books.save_account(v["code"], v["name"], v["type"], v["sub"], v["desc"], a.get("id"))).show()
        if v:
            self.refresh()

    def new_account(self):
        self._acc_form()

    def edit_account(self):
        self._acc_form(self._acc())

    def deactivate(self):
        a = self._acc()
        self.books.set_account_active(a["id"], not a["active"])
        self.refresh()

    def opening(self):
        a = self._acc()
        v = FormDialog(self, f"Opening balance: {a['name']}", [
            ("date", "Date", "date", None, (date.today().replace(day=1) - timedelta(days=1)).isoformat()),
            ("amt", "Amount (normal balance; negative to reverse)", "number")],
            lambda v: self.books.opening_balance(v["date"], a["id"], v["amt"])).show()
        if v:
            self.app.refresh()

    def ledger(self):
        a = self._acc()
        self.app.show_page("Reports")
        self.app.pages["Reports"].run_report("General ledger / cash book", account_id=a["id"])

    def _jid(self):
        i = self.jr.selected()
        if not i:
            raise AccError("Select a journal entry first.")
        return int(i)

    def view(self):
        self.app.show_entry(self._jid())

    def reverse(self):
        jid = self._jid()
        if confirm(self, "Post a reversing entry dated today for this journal?"):
            self.books.reverse_manual_journal(jid)
            self.app.refresh()

    def new_dept(self):
        self.books.need_module("departments")
        v = FormDialog(self, "New department", [("name", "Name", "entry")],
                       lambda v: self.books.save_department(v["name"])).show()
        if v:
            self.refresh()

    def edit_dept(self):
        i = self.depts.selected()
        if not i:
            raise AccError("Select a department first.")
        d = self.books.one("SELECT * FROM departments WHERE id=?", (int(i),))
        v = FormDialog(self, "Department", [("name", "Name", "entry", None, d["name"]),
                                            ("active", "Active", "check", None, d["active"])],
                       lambda v: self.books.save_department(v["name"], d["id"], v["active"])).show()
        if v:
            self.refresh()


# ====================================================================== reports
REPORTS = [
    ("Profit and loss", "range"), ("Profit and loss by department", "range"), ("Balance sheet", "asof"),
    ("Trial balance", "asof"), ("General ledger / cash book", "range_account"), ("Debtors aging", "asof"),
    ("Creditors aging", "asof"), ("VAT summary", "range"), ("Customer / supplier statement", "range_contact"),
    ("Inventory valuation", "none"), ("Sales by customer", "range"), ("Tourism levy summary", "range"),
    ("Withholding tax summary", "range"),
]


class ReportsPage(Page):
    title = "Reports"

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.action("Export CSV", self.export)
        self.action("Print / PDF", self.print_, True)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        left = Card(body, "Reports")
        left.pack(side="left", fill="y")
        self.listbox = tk.Listbox(left, font=f(10), relief="flat", highlightthickness=0, activestyle="none",
                                  selectbackground="#CFE8DD", selectforeground=C.NAVY, width=31, height=18,
                                  bd=0)
        for name, _ in REPORTS:
            self.listbox.insert("end", name)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._select())
        right = Card(body)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.params = ttk.Frame(right, style="Card.TFrame")
        self.params.pack(fill="x", pady=(0, 10))
        s, e = date.today().replace(day=1).isoformat(), date.today().isoformat()
        self.start, self.end = tk.StringVar(value=s), tk.StringVar(value=e)
        self.sel = tk.StringVar()
        self.title_lbl = ttk.Label(right, text="", style="H2.TLabel")
        self.title_lbl.pack(anchor="w")
        self.table_holder = ttk.Frame(right, style="Card.TFrame")
        self.table_holder.pack(fill="both", expand=True, pady=(6, 0))
        self.current = None
        self.output = None
        self.listbox.selection_set(0)
        self._select()

    def _select(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        name, kind = REPORTS[sel[0]]
        self.current = name
        for w in self.params.winfo_children():
            w.destroy()
        col = 0

        def add(label, widget):
            nonlocal col
            ttk.Label(self.params, text=label, style="CardMuted.TLabel").grid(row=0, column=col, sticky="w", padx=(0, 8))
            widget.grid(row=1, column=col, sticky="w", padx=(0, 8))
            col += 1
        if kind.startswith("range"):
            add("From", ttk.Entry(self.params, textvariable=self.start, width=12))
            add("To", ttk.Entry(self.params, textvariable=self.end, width=12))
        elif kind == "asof":
            add("As at", ttk.Entry(self.params, textvariable=self.end, width=12))
        self.options = []
        if kind == "range_account":
            self.options = [(a["id"], f"{a['code']}  {a['name']}") for a in self.books.accounts()]
        elif kind == "range_contact":
            self.options = [(c["id"], f"{c['name']} ({c['kind']})") for c in
                            list(self.books.contacts("customer")) + list(self.books.contacts("supplier"))]
        if self.options:
            if self.sel.get() not in [o[1] for o in self.options]:
                self.sel.set(self.options[0][1])
            add("Account" if kind == "range_account" else "Contact",
                ttk.Combobox(self.params, textvariable=self.sel, values=[o[1] for o in self.options],
                             state="readonly", width=40))
        ttk.Button(self.params, text="Run report", style="Primary.TButton",
                   command=self._safe(self.run)).grid(row=1, column=col)
        if kind.startswith("range"):
            q = ttk.Frame(self.params, style="Card.TFrame")
            q.grid(row=2, column=0, columnspan=col + 1, sticky="w", pady=(8, 0))
            for text, fn in [("This month", self._this_month), ("Last month", self._last_month),
                             ("This year", self._this_year)]:
                ttk.Button(q, text=text, command=fn).pack(side="left", padx=(0, 4))
        self.run()

    def _this_month(self):
        self.start.set(date.today().replace(day=1).isoformat()); self.end.set(date.today().isoformat()); self.run()

    def _last_month(self):
        e = date.today().replace(day=1) - timedelta(days=1)
        self.start.set(e.replace(day=1).isoformat()); self.end.set(e.isoformat()); self.run()

    def _this_year(self):
        s, e = self.books.fy_bounds()
        self.start.set(s); self.end.set(min(e, date.today().isoformat())); self.run()

    def run_report(self, name, account_id=None, contact_id=None):
        idx = [r[0] for r in REPORTS].index(name)
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(idx)
        self._select()
        target = account_id or contact_id
        if target:
            lab = next((o[1] for o in self.options if o[0] == target), None)
            if lab:
                self.sel.set(lab)
        self.start.set((date.today() - timedelta(days=90)).isoformat())
        self.run()

    def _sel_id(self):
        return next((o[0] for o in self.options if o[1] == self.sel.get()), None)

    def run(self):
        if not (valid_date(self.start.get()) and valid_date(self.end.get())):
            raise AccError("Dates must be in the format YYYY-MM-DD.")
        s, e, b = self.start.get(), self.end.get(), self.books
        name = self.current
        money_idx = []
        if name == "Profit and loss":
            pl = b.profit_loss(s, e)
            headers, money_idx = ["Code", "Account", "Amount"], [2]
            rows = [("__section__", "Income")] + [[r["code"], r["name"], r["amount"]] for r in pl["income"]]
            rows += [("__total__", ["", "Total income", pl["total_income"]])]
            if pl["cogs"]:
                rows += [("__section__", "Cost of sales")] + [[r["code"], r["name"], r["amount"]] for r in pl["cogs"]]
                rows += [("__total__", ["", "Gross profit", pl["gross_profit"]])]
            rows += [("__section__", "Operating expenses")] + [[r["code"], r["name"], r["amount"]] for r in pl["expenses"]]
            rows += [("__total__", ["", "Total expenses", pl["total_expenses"]]),
                     ("__total__", ["", "NET PROFIT / (LOSS)", pl["net_profit"]])]
            sub = f"{s} to {e}"
        elif name == "Profit and loss by department":
            headers, money_idx = ["Department", "Income", "Costs", "Profit"], [1, 2, 3]
            data = b.department_pl(s, e)
            rows = [[r["department"], r["income"], r["costs"], r["profit"]] for r in data]
            pl = b.profit_loss(s, e)
            unassigned = pl["net_profit"] - sum(r["profit"] for r in data)
            rows.append(["(Not assigned to a department)", "", "", round(unassigned, 2)])
            rows.append(("__total__", ["Total", pl["total_income"], pl["total_cogs"] + pl["total_expenses"],
                                       pl["net_profit"]]))
            sub = f"{s} to {e}"
        elif name == "Balance sheet":
            bs = b.balance_sheet(e)
            headers, money_idx = ["Code", "Account", "Amount"], [2]
            rows = [("__section__", "Assets")] + [[r["code"], r["name"], r["amount"]] for r in bs["assets"]]
            rows += [("__total__", ["", "Total assets", bs["total_assets"]]), ("__section__", "Liabilities")]
            rows += [[r["code"], r["name"], r["amount"]] for r in bs["liabilities"]]
            rows += [("__total__", ["", "Total liabilities", bs["total_liabilities"]]), ("__section__", "Equity")]
            rows += [[r["code"], r["name"], r["amount"]] for r in bs["equity"]]
            rows += [("__total__", ["", "Total equity", bs["total_equity"]]),
                     ("__total__", ["", "Liabilities + equity", bs["total_liabilities"] + bs["total_equity"]])]
            sub = f"As at {e}"
        elif name == "Trial balance":
            tb = b.trial_balance(e)
            headers, money_idx = ["Code", "Account", "Debit", "Credit"], [2, 3]
            rows = [[r["code"], r["name"], r["debit"] or "", r["credit"] or ""] for r in tb["rows"]]
            rows.append(("__total__", ["", "Totals", tb["total_debit"], tb["total_credit"]]))
            sub = f"As at {e}"
        elif name == "General ledger / cash book":
            gl = b.general_ledger(self._sel_id(), s, e)
            headers, money_idx = ["Date", "Ref", "Details", "Department", "Debit", "Credit", "Balance"], [4, 5, 6]
            rows = [["", "", "Opening balance", "", "", "", gl["opening"]]]
            rows += [[r["date"], r["ref"], r["memo"], r["department"] or "", r["debit"] or "", r["credit"] or "",
                      r["balance"]] for r in gl["rows"]]
            rows.append(("__total__", ["", "", "Closing balance", "", "", "", gl["closing"]]))
            sub = f"{gl['account']['code']} {gl['account']['name']} \u00b7 {s} to {e}"
        elif name in ("Debtors aging", "Creditors aging"):
            ag = b.aging("sale" if name == "Debtors aging" else "bill", e)
            headers = ["Name"] + ag["buckets"] + ["Total"]
            money_idx = list(range(1, len(headers)))
            rows = [[r["contact"]] + [r[k] for k in ag["buckets"] + ["Total"]] for r in ag["rows"]]
            rows.append(("__total__", ["Total"] + [ag["totals"][k] for k in ag["buckets"] + ["Total"]]))
            sub = f"As at {e} (days past due)"
        elif name == "VAT summary":
            v = b.vat_summary(s, e)
            headers, money_idx = ["Item", "Amount"], [1]
            rows = [["Sales (net of VAT)", v["sales_net"]], ["Output VAT charged", v["output_vat"]],
                    ["Purchases (net of VAT)", v["purchases_net"]], ["Input VAT claimable", v["input_vat"]],
                    ("__total__", ["Net VAT payable / (refundable)", v["net_vat"]])]
            sub = f"{s} to {e} \u00b7 VAT rate {b.vat_rate:g}%"
        elif name == "Customer / supplier statement":
            cid = self._sel_id()
            if not cid:
                raise AccError("Add a customer or supplier first.")
            st = b.customer_statement(cid, s, e)
            headers, money_idx = ["Date", "Ref", "Type", "Amount", "Balance"], [3, 4]
            rows = [["", "", "Opening balance", "", st["opening"]]]
            rows += [[r["date"], r["ref"], r["type"], r["amount"], r["balance"]] for r in st["rows"]]
            rows.append(("__total__", ["", "", "Balance due", "", st["closing"]]))
            sub = f"{st['contact']['name']} \u00b7 {s} to {e}"
        elif name == "Inventory valuation":
            iv = b.inventory_valuation()
            headers, money_idx = ["Code", "Item", "Unit", "On hand", "Avg cost", "Value"], [4, 5]
            rows = [[r["code"], r["name"] + ("  (reorder)" if r["low"] else ""), r["unit"], f"{r['qty']:g}",
                     r["cost"], r["value"]] for r in iv["rows"]]
            rows.append(("__total__", ["", "Total stock value", "", "", "", iv["total"]]))
            sub = f"As at {date.today().isoformat()}"
        elif name == "Tourism levy summary":
            t = b.tourism_summary(s, e)
            headers, money_idx = ["Month", "Documents", "Sales subject to levy", "Levy charged", "Levy paid"], [2, 3, 4]
            rows = [[date.fromisoformat(r["month"] + "-01").strftime("%B %Y"), r["docs"], r["base"], r["levy"],
                     r["paid"]] for r in t["rows"]]
            rows.append(("__total__", ["Total", sum(r["docs"] for r in t["rows"]), t["total_base"], t["total_levy"],
                                       t["total_paid"]]))
            if t["departments"]:
                rows.append(("__section__", "By department"))
                rows += [[d["department"], "", d["base"], d["levy"], ""] for d in t["departments"]]
            rows.append(("__total__", [f"Levy owed to the Ministry of Tourism at {e}", "", "", t["owed"], ""]))
            sub = f"{s} to {e} \u00b7 levy rate {t['rate']:g}%"
        elif name == "Withholding tax summary":
            w = b.wht_summary(s, e)
            headers, money_idx = ["Name", "Payments", "Amount settled", "Withholding tax"], [2, 3]
            rows = [("__section__", "Deducted from suppliers (pay to MRA)")]
            rows += [[r["name"], r["count"], r["settled"], r["wht"]] for r in w["deducted"]]
            rows.append(("__total__", ["Total deducted", "", "", w["total_deducted"]]))
            rows.append(["Paid to MRA in this period", "", "", w["paid"]])
            rows.append(("__total__", [f"Owed to MRA at {e} (payable annually)", "", "", w["owed"]]))
            rows.append(("__section__", "Withheld by customers (claim with certificates)"))
            rows += [[r["name"], r["count"], "", r["wht"]] for r in w["certificates"]]
            rows.append(("__total__", ["Total certificates due", "", "", w["certificates_total"]]))
            sub = f"{s} to {e} \u00b7 financial year {w['fy'][0]} to {w['fy'][1]}"
        elif name == "Sales by customer":
            data = b.q("SELECT c.name, COUNT(*) n, SUM(i.subtotal) net, SUM(i.vat) vat, SUM(i.total) tot "
                       "FROM invoices i JOIN contacts c ON c.id=i.contact_id WHERE i.kind='sale' AND i.status<>'void' "
                       "AND i.date BETWEEN ? AND ? GROUP BY c.id ORDER BY tot DESC", (s, e))
            headers, money_idx = ["Customer", "Invoices", "Net", "VAT", "Total"], [2, 3, 4]
            rows = [[r["name"], r["n"], r["net"], r["vat"], r["tot"]] for r in data]
            rows.append(("__total__", ["Total", sum(r["n"] for r in data), sum(r["net"] for r in data),
                                       sum(r["vat"] for r in data), sum(r["tot"] for r in data)]))
            sub = f"{s} to {e}"
        else:
            return
        self.output = (name, sub, headers, rows, money_idx)
        self._render()

    def _render(self):
        name, sub, headers, rows, money_idx = self.output
        self.title_lbl.configure(text=f"{name}  \u00b7  {sub}")
        for w in self.table_holder.winfo_children():
            w.destroy()
        widths = [120 if i in money_idx else max(90, min(360, 11 * len(h) + 40)) for i, h in enumerate(headers)]
        text_cols = [i for i in range(len(headers)) if i not in money_idx]
        if text_cols:
            main_col = 1 if len(text_cols) > 1 and headers[0] in ("Code", "Date") else text_cols[0]
            widths[main_col] = 300
        cols = [(f"c{i}", h, widths[i], "e" if i in money_idx else "w") for i, h in enumerate(headers)]
        t = Table(self.table_holder, cols, height=18)
        t.pack(fill="both", expand=True)
        vals, tags = [], []
        for r in rows:
            if r and r[0] == "__section__":
                vals.append([r[1].upper()] + [""] * (len(headers) - 1)); tags.append(("bold",))
            elif r and r[0] == "__total__":
                vals.append([money(v) if i in money_idx and isinstance(v, (int, float)) else v
                             for i, v in enumerate(r[1])]); tags.append(("bold",))
            else:
                vals.append([money(v) if i in money_idx and isinstance(v, (int, float)) else v
                             for i, v in enumerate(r)]); tags.append(())
        t.set_rows(vals, tags=tags)

    def _flat(self):
        name, sub, headers, rows, money_idx = self.output
        out = []
        for r in rows:
            if r and r[0] == "__section__":
                out.append([r[1]] + [""] * (len(headers) - 1))
            elif r and r[0] == "__total__":
                out.append(list(r[1]))
            else:
                out.append(list(r))
        return out

    def export(self):
        if not self.output:
            return
        name, sub, headers, rows, _ = self.output
        default = f"{name.replace('/', '-')} {date.today().isoformat()}.csv"
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile=default,
                                            initialdir=str(C.data_dir() / "exports"), filetypes=[("CSV", "*.csv")])
        if path:
            export_csv(path, headers, self._flat())
            info(self, f"Exported to {path}")

    def print_(self):
        if self.output and self.current == "Customer / supplier statement" and self._sel_id():
            printing.print_statement(self.books, self._sel_id(), self.start.get(), self.end.get())
            return
        if self.output:
            name, sub, headers, rows, money_idx = self.output
            printing.print_report(self.books, name, sub, headers, rows, money_idx)

    def refresh(self):
        if self.current:
            try:
                self.run()
            except AccError:
                pass


# ====================================================================== settings
class SettingsPage(Page):
    title = "Settings"

    def __init__(self, parent, app):
        super().__init__(parent, app)
        nb = ColorTabs(self)
        nb.pack(fill="both", expand=True)
        self.nb = nb
        # company
        t = Card(nb)
        nb.add(t, text="Company")
        self.co_lbl = ttk.Label(t, text="", style="Card.TLabel", justify="left")
        self.co_lbl.pack(anchor="w")
        bar = ttk.Frame(t, style="Card.TFrame")
        bar.pack(anchor="w", pady=10)
        ttk.Button(bar, text="Edit company details", style="Primary.TButton",
                   command=self._safe(self.edit_company)).pack(side="left")
        ttk.Button(bar, text="Upload logo...", command=self._safe(self.upload_logo)).pack(side="left", padx=6)
        ttk.Button(bar, text="Remove logo", command=self._safe(self.remove_logo)).pack(side="left")
        # bank details
        t = Card(nb, "Bank details printed on invoices, quotations, receipts and statements")
        nb.add(t, text="Bank details")
        grid = ttk.Frame(t, style="Card.TFrame")
        grid.pack(anchor="w")
        self.bank_vars = []
        labels = [("name", "Bank"), ("branch", "Branch"), ("account_name", "Account name"),
                  ("account_no", "Account number")]
        for n in range(3):
            col = ttk.Frame(grid, style="Card.TFrame")
            col.grid(row=0, column=n, sticky="n", padx=(0, 28))
            ttk.Label(col, text=f"BANK {n + 1}" + ("" if n < 2 else " (optional)"), style="Card.TLabel",
                      font=f(10, "bold"), foreground=C.EMERALD).pack(anchor="w", pady=(0, 6))
            vs = {}
            for key, lab in labels:
                ttk.Label(col, text=lab, style="CardMuted.TLabel").pack(anchor="w")
                vs[key] = tk.StringVar()
                ttk.Entry(col, textvariable=vs[key], width=28).pack(anchor="w", pady=(2, 8))
            self.bank_vars.append(vs)
        ttk.Label(t, text="Mobile money (e.g. Airtel Money 0999 000 000 \u00b7 TNM Mpamba 0888 000 000)",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(6, 0))
        self.mm_var = tk.StringVar()
        ttk.Entry(t, textvariable=self.mm_var, width=90).pack(anchor="w", pady=(2, 12))
        ttk.Button(t, text="Save bank details", style="Primary.TButton",
                   command=self._safe(self.save_banks)).pack(anchor="w")
        # users
        t = Card(nb)
        nb.add(t, text="Users")
        bar = ttk.Frame(t, style="Card.TFrame")
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="New user", style="Primary.TButton", command=self._safe(self.new_user)).pack(side="left")
        ttk.Button(bar, text="Edit user", command=self._safe(self.edit_user)).pack(side="left", padx=6)
        ttk.Button(bar, text="Change my password", command=self._safe(self.my_password)).pack(side="left")
        self.user_lbl = ttk.Label(bar, text="", style="CardMuted.TLabel")
        self.user_lbl.pack(side="right")
        self.users = Table(t, [("u", "Username", 140, "w"), ("n", "Full name", 220, "w"), ("r", "Role", 130, "w"),
                               ("a", "Active", 70, "center"), ("c", "Created", 160, "w")],
                           on_double=lambda i: self.edit_user())
        self.users.pack(fill="both", expand=True)
        # licence
        self.lic_tab = Card(nb)
        nb.add(self.lic_tab, text="Licence")
        self.lic_body = ttk.Frame(self.lic_tab, style="Card.TFrame")
        self.lic_body.pack(fill="both", expand=True)
        # backup
        t = Card(nb)
        nb.add(t, text="Backup and restore")
        ttk.Label(t, text="Back up at least once a day and keep a copy off this computer (flash disk or cloud).",
                  style="CardMuted.TLabel").pack(anchor="w")
        bar = ttk.Frame(t, style="Card.TFrame")
        bar.pack(anchor="w", pady=10)
        ttk.Button(bar, text="Back up now", style="Primary.TButton", command=self._safe(self.backup)).pack(side="left")
        ttk.Button(bar, text="Back up to folder...", command=self._safe(self.backup_to)).pack(side="left", padx=6)
        ttk.Button(bar, text="Restore from backup...", command=self._safe(self.restore)).pack(side="left")
        self.bk = Table(t, [("f", "Backup file", 420, "w"), ("s", "Size", 90, "e"), ("d", "Created", 170, "w")], height=8)
        self.bk.pack(fill="both", expand=True)
        # period close
        t = Card(nb)
        nb.add(t, text="Period close")
        self.lock_lbl = ttk.Label(t, text="", style="Card.TLabel")
        self.lock_lbl.pack(anchor="w")
        bar = ttk.Frame(t, style="Card.TFrame")
        bar.pack(anchor="w", pady=10)
        ttk.Button(bar, text="Set lock date...", command=self._safe(self.lock)).pack(side="left")
        ttk.Button(bar, text="Close financial year...", style="Primary.TButton",
                   command=self._safe(self.close_year)).pack(side="left", padx=6)
        ttk.Label(t, text="Closing a year moves its profit or loss into Retained Earnings and locks all entries "
                          "up to the year-end date.", style="CardMuted.TLabel").pack(anchor="w")
        # audit
        self.audit_tab = Card(nb)
        nb.add(self.audit_tab, text="Audit trail")
        self.audit_search, _ = search_bar(self.audit_tab, self.refresh)
        self.audit = Table(self.audit_tab, [("t", "Time", 150, "w"), ("u", "User", 100, "w"), ("a", "Action", 90, "w"),
                                            ("e", "Record", 100, "w"), ("i", "ID", 60, "e"),
                                            ("d", "Details", 380, "w")])
        self.audit.pack(fill="both", expand=True)
        self.audit_msg = ttk.Label(self.audit_tab, text="", style="CardMuted.TLabel")
        self.audit_msg.pack(anchor="w")
        # about
        t = Card(nb)
        nb.add(t, text="About")
        ttk.Label(t, text=f"{C.APP_NAME}  version {C.VERSION}", style="H2.TLabel").pack(anchor="w")
        ttk.Label(t, text=f"{C.VENDOR}\n{C.VENDOR_PHONE}  \u00b7  {C.VENDOR_EMAIL}\n\nData folder: {C.data_dir()}",
                  style="Card.TLabel", justify="left").pack(anchor="w", pady=8)
        ttk.Button(t, text="Check for updates", command=self.app.check_updates).pack(anchor="w")

    def refresh(self):
        co = self.books.company()
        self.co_lbl.configure(text="\n".join(f"{k.replace('_', ' ').title()}:  {v}" for k, v in co.items()
                                             if k not in ("lock_date", "industry", "currency") and
                                             not k.startswith("bank") and k != "mobile_money"))
        for vs, b in zip(self.bank_vars, self.books.banks()):
            for k, var in vs.items():
                var.set(b.get(k, ""))
        self.mm_var.set(self.books.setting("mobile_money", "") or "")
        us = self.books.users()
        self.users.set_rows([[u["username"], u["full_name"], u["role"], "Yes" if u["active"] else "No", u["created_at"]]
                             for u in us], ids=[u["id"] for u in us])
        st = self.books.license()
        mx = st.max_users if st else 0
        self.user_lbl.configure(text=f"Active users: {sum(1 for u in us if u['active'])} of "
                                     f"{'unlimited' if not mx else mx} allowed by your licence")
        self.render_licence()
        bdir = C.data_dir() / "backups"
        files = sorted(bdir.glob("*.bak"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]
        from datetime import datetime
        self.bk.set_rows([[p.name, f"{p.stat().st_size / 1024:,.0f} KB",
                           datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")] for p in files])
        lock = self.books.setting("lock_date", "")
        s, e = self.books.fy_bounds()
        self.lock_lbl.configure(text=f"Entries locked up to: {lock or 'not locked'}\nCurrent financial year: {s} to {e}")
        if self.books.has_module("audit_viewer"):
            logs = self.books.audit_trail(search=self.audit_search.get())
            self.audit.set_rows([[l["ts"], l["username"], l["action"], l["entity"], l["entity_id"], l["details"]]
                                 for l in logs])
            self.audit_msg.configure(text="")
        else:
            self.audit.set_rows([])
            self.audit_msg.configure(text="Every action is recorded. The audit trail viewer is part of the "
                                          "Enterprise package.")

    def render_licence(self):
        for w in self.lic_body.winfo_children():
            w.destroy()
        st = self.app.lic_status()
        colour = {licensing.ACTIVE: C.EMERALD, licensing.TRIAL: C.WARNING, licensing.REMINDER: C.WARNING,
                  licensing.GRACE: C.DANGER, licensing.READONLY: C.DANGER}.get(st.state, C.MUTED)
        ttk.Label(self.lic_body, text=st.state.upper(), style="Card.TLabel", foreground=colour,
                  font=f(11, "bold")).pack(anchor="w")
        ttk.Label(self.lic_body, text=st.message, style="Card.TLabel", wraplength=760).pack(anchor="w", pady=(2, 10))
        rows = [("Machine ID", licensing.this_machine_id())]
        if st.info:
            i = st.info
            rows += [("Package", i.plan_name), ("Users", i.users_label), ("Licence no.", f"{i.serial:06d}"),
                     ("Issued", i.issued.strftime("%d %b %Y")), ("Valid until", i.expires.strftime("%d %b %Y"))]
        rows.append(("Modules", ", ".join(m.replace("_", " ") for m in st.modules)))
        g = ttk.Frame(self.lic_body, style="Card.TFrame")
        g.pack(anchor="w")
        for r, (k, v) in enumerate(rows):
            ttk.Label(g, text=k, style="CardMuted.TLabel").grid(row=r, column=0, sticky="w", pady=2, padx=(0, 20))
            ttk.Label(g, text=v, style="Card.TLabel", font=f(10, "bold")).grid(row=r, column=1, sticky="w")
        bar = ttk.Frame(self.lic_body, style="Card.TFrame")
        bar.pack(anchor="w", pady=12)
        ttk.Button(bar, text="Enter renewal key", style="Primary.TButton",
                   command=self.app.enter_key).pack(side="left")
        ttk.Button(bar, text="Copy Machine ID", command=self.copy_mid).pack(side="left", padx=6)
        pk = "   ".join(f"{p['name']}: MWK {p['monthly']:,}/month" for p in plans.PLANS.values())
        ttk.Label(self.lic_body, text=f"Packages \u2014 {pk}\nTo renew or upgrade call {C.VENDOR_PHONE} or email "
                                      f"{C.VENDOR_EMAIL} with your Machine ID.", style="CardMuted.TLabel",
                  justify="left").pack(anchor="w")

    def save_banks(self):
        banks = [{k: var.get() for k, var in vs.items()} for vs in self.bank_vars]
        filled = [b for b in banks if b["name"].strip() and b["account_no"].strip()]
        if len(filled) < 2 and not confirm(self, "Fewer than two banks have a name and account number. "
                                                 "Save anyway?"):
            return
        self.books.save_banks(banks, self.mm_var.get())
        info(self, "Bank details saved. They now print on all customer documents.")

    def copy_mid(self):
        self.clipboard_clear()
        self.clipboard_append(licensing.this_machine_id())
        info(self, "Machine ID copied. Send it to Nolima Tech Consultants with your payment reference.")

    def edit_company(self):
        co = self.books.company()
        months = [(i, date(2000, i, 1).strftime("%B")) for i in range(1, 13)]
        v = FormDialog(self, "Company details", [
            ("company_name", "Company name", "entry", None, co["company_name"]),
            ("address", "Address", "text", None, co["address"]), ("phone", "Phone", "entry", None, co["phone"]),
            ("email", "Email", "entry", None, co["email"]), ("tpin", "TPIN", "entry", None, co["tpin"]),
            ("vat_rate", "VAT rate (%)", "number", None, co["vat_rate"]),
            ("tourism_levy_rate", "Tourism levy (%) on sales", "number", None, co["tourism_levy_rate"] or 0),
            ("profit_method", "How profit is calculated", "combo",
             [("expense", "From expenses: stock is an expense when bought"),
              ("cogs", "From cost of sales: stock is an expense when sold")],
             self.books.setting("profit_method", "expense")),
            ("inv_prefix", "Invoice number prefix (blank = plain numbers)", "entry", None,
             self.books.setting("inv_prefix", "")),
            ("inv_start", "Next invoice number (at least)", "entry", None, self.books.setting("inv_start", "1")),
            ("quote_prefix", "Quotation number prefix (blank = plain numbers)", "entry", None,
             self.books.setting("quote_prefix", "")),
            ("quote_start", "Next quotation number (at least)", "entry", None, self.books.setting("quote_start", "1")),
            ("fy_start_month", "Financial year starts", "combo", months, int(co["fy_start_month"] or 1)),
            ("payment_terms", "Payment terms on invoices", "entry", None, co["payment_terms"])],
            self._save_company).show()
        if v:
            self.app.refresh()

    def _save_company(self, v):
        method = v.pop("profit_method")
        for k in ("inv_start", "quote_start"):
            if not str(v[k]).strip().isdigit():
                raise AccError("Next numbers must be whole numbers, for example 1878.")
        self.books.update_company(**v)
        if method != self.books.setting("profit_method", "expense"):
            move = False
            inv_bal = self.books.balance(self.books.account_by_subtype("inventory")["id"])
            if method == "expense" and abs(inv_bal) > 0.005:
                move = confirm(self, f"Stock worth MWK {money(inv_bal)} is still held as Inventory. Move it into "
                                     "expenses now, so profit is calculated from expenses from today?")
            self.books.set_profit_method(method, move)
        return True

    def upload_logo(self):
        p = filedialog.askopenfilename(parent=self, title="Choose your logo",
                                       filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp")])
        if not p:
            return
        import base64
        import io
        from PIL import Image
        im = Image.open(p).convert("RGBA")
        im.thumbnail((480, 200))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        self.books.set_setting("logo_png", base64.b64encode(buf.getvalue()).decode())
        info(self, "Logo saved. It now prints on invoices and quotations.")

    def remove_logo(self):
        self.books.set_setting("logo_png", "")
        info(self, "Logo removed.")

    def new_user(self):
        v = FormDialog(self, "New user", [
            ("username", "Username", "entry"), ("full_name", "Full name", "entry"),
            ("role", "Role", "combo", [(r, r) for r in ROLES], "Cashier"), ("pw", "Password", "password"),
            ("pw2", "Confirm password", "password")], self._create_user).show()
        if v:
            self.refresh()

    def _create_user(self, v):
        if v["pw"] != v["pw2"]:
            raise AccError("Passwords do not match.")
        return self.books.create_user(v["username"], v["pw"], v["role"], v["full_name"])

    def edit_user(self):
        i = self.users.selected()
        if not i:
            raise AccError("Select a user first.")
        u = self.books.one("SELECT * FROM users WHERE id=?", (int(i),))
        v = FormDialog(self, f"Edit user {u['username']}", [
            ("full_name", "Full name", "entry", None, u["full_name"]),
            ("role", "Role", "combo", [(r, r) for r in ROLES], u["role"]),
            ("active", "Active", "check", None, u["active"]), ("pw", "New password (optional)", "password")],
            lambda v: self.books.update_user(u["id"], v["role"], v["full_name"], v["active"], v["pw"] or None)).show()
        if v:
            self.refresh()

    def my_password(self):
        v = FormDialog(self, "Change my password", [("old", "Current password", "password"),
                                                     ("new", "New password", "password"),
                                                     ("new2", "Confirm", "password")], self._chpw).show()
        if v:
            info(self, "Password changed.")

    def _chpw(self, v):
        if v["new"] != v["new2"]:
            raise AccError("Passwords do not match.")
        self.books.change_own_password(v["old"], v["new"])
        return True

    def backup(self):
        p = self.books.backup(C.data_dir() / "backups")
        self.refresh()
        info(self, f"Backup saved:\n{p}")

    def backup_to(self):
        d = filedialog.askdirectory(parent=self, title="Choose backup folder (e.g. flash disk)")
        if d:
            p = self.books.backup(d)
            info(self, f"Backup saved:\n{p}")

    def restore(self):
        self.books.require("setup")
        p = filedialog.askopenfilename(parent=self, initialdir=str(C.data_dir() / "backups"),
                                       filetypes=[("Nolima backup", "*.bak *.nacc"), ("All files", "*.*")])
        if p and confirm(self, "Restoring replaces ALL current data with the backup. A safety copy of the current "
                               "data is kept. Continue?"):
            self.app.restore_backup(Path(p))

    def lock(self):
        v = FormDialog(self, "Lock date", [("d", "Lock all entries up to (blank to unlock)", "entry", None,
                                            self.books.setting("lock_date", ""))],
                       lambda v: self.books.set_lock_date(v["d"])).show()
        if v:
            self.refresh()

    def close_year(self):
        s, e = self.books.fy_bounds((date.today().replace(month=1, day=1) - timedelta(days=1)).isoformat()
                                    if date.today().month < 6 else None)
        v = FormDialog(self, "Close financial year", [("end", "Year-end date", "date", None, e)]).show()
        if v and confirm(self, f"Close the year ending {v['end']}? Entries up to that date will be locked."):
            net = self.books.close_year(v["end"])
            info(self, f"Year closed. Net profit of MWK {money(net)} moved to Retained Earnings.")
            self.app.refresh()
