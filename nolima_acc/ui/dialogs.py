"""Data-entry dialogs for financial documents."""
import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk

from .. import config as C
from ..services import AccError
from .theme import f, money
from .widgets import Dialog, FormDialog, LinesEditor, Table, confirm, error, num, valid_date


def contact_form(parent, books, kind, contact=None):
    c = contact or {}
    fields = [("name", "Name", "entry", None, c.get("name")),
              ("phone", "Phone", "entry", None, c.get("phone")),
              ("email", "Email", "entry", None, c.get("email")),
              ("address", "Address", "text", None, c.get("address")),
              ("tpin", "TPIN", "entry", None, c.get("tpin"))]
    if contact:
        fields.append(("active", "Active", "check", None, c.get("active", 1)))

    def save(v):
        return books.save_contact(kind, v["name"], v["phone"], v["email"], v["address"], v["tpin"],
                                  contact_id=c.get("id"), active=v.get("active", True))
    title = ("Edit " if contact else "New ") + kind
    return FormDialog(parent, title.title(), fields, save).show()


class _Header(ttk.Frame):
    """Row of labelled inputs used at the top of document dialogs."""

    def __init__(self, parent):
        super().__init__(parent, style="Card.TFrame")
        self.col = 0

    def add(self, label, widget):
        ttk.Label(self, text=label, style="CardMuted.TLabel").grid(row=0, column=self.col, sticky="w", padx=(0, 10))
        widget.grid(row=1, column=self.col, sticky="ew", padx=(0, 10), pady=(2, 10))
        self.col += 1
        return widget


class InvoiceDialog(Dialog):
    """kind: 'sale' | 'bill'; cash=True makes a cash sale (paid immediately)."""

    def __init__(self, parent, books, kind="sale", cash=False):
        title = "Cash sale" if cash else ("New invoice" if kind == "sale" else "New supplier bill")
        super().__init__(parent, title, width=1000)
        self.books, self.kind, self.cash = books, kind, cash
        ckind = "customer" if kind == "sale" else "supplier"
        self.ckind = ckind
        hdr = _Header(self.body)
        hdr.pack(fill="x")
        self.contact = tk.StringVar()
        self.contact_cb = hdr.add("Customer" if kind == "sale" else "Supplier",
                                  ttk.Combobox(hdr, textvariable=self.contact, state="readonly", width=30))
        ttk.Button(hdr, text="+ New", command=self.new_contact).grid(row=1, column=hdr.col, padx=(0, 16), pady=(2, 10))
        hdr.col += 1
        self.date = tk.StringVar(value=date.today().isoformat())
        hdr.add("Date", ttk.Entry(hdr, textvariable=self.date, width=12))
        self.due = tk.StringVar(value=(date.today() + timedelta(days=30)).isoformat())
        if not cash:
            hdr.add("Due date", ttk.Entry(hdr, textvariable=self.due, width=12))
        self.ref = tk.StringVar()
        hdr.add("Reference" if kind == "sale" else "Supplier invoice no.", ttk.Entry(hdr, textvariable=self.ref, width=16))
        if cash:
            self.banks = [(a["id"], a["name"]) for a in books.bank_accounts()]
            self.bank = tk.StringVar(value=self.banks[0][1] if self.banks else "")
            hdr.add("Paid into", ttk.Combobox(hdr, textvariable=self.bank, values=[b[1] for b in self.banks],
                                              state="readonly", width=26))
        self.inc = tk.BooleanVar(value=cash)
        ttk.Checkbutton(self.body, text="Prices include VAT", variable=self.inc, style="Card.TCheckbutton",
                        command=self.update_totals).pack(anchor="w")
        self.lines = LinesEditor(self.body, books, "sale" if kind == "sale" else "bill")
        self.lines.pack(fill="both", expand=True, pady=8)
        if kind == "bill":
            ttk.Label(self.body, text="Stock items bought go into Inventory. Their cost becomes an expense (cost of "
                                      "sales) when they are sold using the same item.", style="CardMuted.TLabel"
                      ).pack(anchor="w")
        self.lines.on_change = self.update_totals
        self.memo = tk.StringVar()
        m = ttk.Frame(self.body, style="Card.TFrame")
        m.pack(fill="x")
        ttk.Label(m, text="Notes", style="CardMuted.TLabel").pack(side="left")
        ttk.Entry(m, textvariable=self.memo).pack(side="left", fill="x", expand=True, padx=8)
        self.totals = ttk.Label(self.buttons, text="", style="Card.TLabel", font=f(12, "bold"))
        self.totals.pack(side="left")
        ttk.Button(self.buttons, text="Save and print", command=lambda: self.save(True)).pack(side="right")
        ttk.Button(self.buttons, text="Save", style="Primary.TButton", command=self.save).pack(side="right", padx=8)
        ttk.Button(self.buttons, text="Cancel", command=self.destroy).pack(side="right")
        self.load_contacts()
        self.update_totals()

    def load_contacts(self, select_id=None):
        self.contacts = [(c["id"], c["name"]) for c in self.books.contacts(self.ckind)]
        self.contact_cb.configure(values=[c[1] for c in self.contacts])
        if select_id:
            self.contact.set(next(c[1] for c in self.contacts if c[0] == select_id))
        elif self.cash and not self.contact.get():
            walk = next((c for c in self.contacts if c[1].lower() in ("walk-in customer", "cash customer")), None)
            if walk:
                self.contact.set(walk[1])

    def new_contact(self):
        cid = contact_form(self, self.books, self.ckind)
        if cid:
            self.load_contacts(cid)

    def update_totals(self):
        net = vat = 0.0
        for l in self.lines.lines:
            g = l["qty"] * l["unit_price"]
            if self.inc.get() and l["vat_rate"]:
                n = g / (1 + l["vat_rate"] / 100)
                net, vat = net + n, vat + g - n
            else:
                net, vat = net + g, vat + g * l["vat_rate"] / 100
        self.totals.configure(text=f"Subtotal {money(net)}    VAT {money(vat)}    Total MWK {money(net + vat)}")

    def save(self, print_after=False):
        cid = next((c[0] for c in self.contacts if c[1] == self.contact.get()), None)
        try:
            if not valid_date(self.date.get()) or (not self.cash and not valid_date(self.due.get())):
                raise AccError("Dates must be in the format YYYY-MM-DD.")
            if self.cash:
                bank = next((b[0] for b in self.banks if b[1] == self.bank.get()), None)
                inv_id = self.books.cash_sale(cid, self.date.get(), self.lines.lines, bank, method=self.bank.get(),
                                              reference=self.ref.get(), memo=self.memo.get(),
                                              prices_inc_vat=self.inc.get())
            else:
                inv_id = self.books.create_invoice(self.kind, cid, self.date.get(), self.lines.lines,
                                                   due_date=self.due.get(), memo=self.memo.get(),
                                                   reference=self.ref.get(), prices_inc_vat=self.inc.get())
        except AccError as exc:
            error(self, exc)
            return
        self.result = inv_id
        if print_after:
            from ..printing import print_invoice
            print_invoice(self.books, inv_id)
        self.destroy()


class PaymentDialog(Dialog):
    """Customer receipt ('receipt') or supplier payment ('payment'), allocated oldest-first."""

    def __init__(self, parent, books, kind="receipt", contact_id=None, invoice_id=None):
        super().__init__(parent, "Receive payment" if kind == "receipt" else "Pay supplier", width=820)
        self.books, self.kind = books, kind
        self.ckind = "customer" if kind == "receipt" else "supplier"
        self.inv_kind = "sale" if kind == "receipt" else "bill"
        self.invoice_first = invoice_id
        hdr = _Header(self.body)
        hdr.pack(fill="x")
        self.contacts = [(c["id"], c["name"]) for c in books.contacts(self.ckind)]
        self.contact = tk.StringVar()
        cb = hdr.add("Customer" if kind == "receipt" else "Supplier",
                     ttk.Combobox(hdr, textvariable=self.contact, values=[c[1] for c in self.contacts],
                                  state="readonly", width=28))
        cb.bind("<<ComboboxSelected>>", lambda e: self.load())
        self.date = tk.StringVar(value=date.today().isoformat())
        hdr.add("Date", ttk.Entry(hdr, textvariable=self.date, width=12))
        self.banks = [(a["id"], a["name"]) for a in books.bank_accounts()]
        self.bank = tk.StringVar(value=self.banks[0][1] if self.banks else "")
        hdr.add("Account", ttk.Combobox(hdr, textvariable=self.bank, values=[b[1] for b in self.banks],
                                        state="readonly", width=28))
        hdr2 = _Header(self.body)
        hdr2.pack(fill="x")
        self.amount = tk.StringVar()
        e = hdr2.add("Amount (MWK)", ttk.Entry(hdr2, textvariable=self.amount, width=16))
        e.bind("<KeyRelease>", lambda ev: self.preview())
        self.method = tk.StringVar(value="Cash")
        hdr2.add("Method", ttk.Combobox(hdr2, textvariable=self.method, width=16,
                                        values=["Cash", "Bank transfer", "Cheque", "Airtel Money", "TNM Mpamba",
                                                "Card", "Other"]))
        self.ref = tk.StringVar()
        hdr2.add("Reference", ttk.Entry(hdr2, textvariable=self.ref, width=20))
        ttk.Label(self.body, text="Unpaid documents (payment is applied to the selected one first, then oldest first)",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(4, 4))
        self.table = Table(self.body, [("num", "Number", 110, "w"), ("date", "Date", 90, "w"),
                                       ("due", "Due", 90, "w"), ("total", "Total", 110, "e"),
                                       ("bal", "Outstanding", 110, "e"), ("apply", "Will apply", 110, "e")], height=7)
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<<TreeviewSelect>>", lambda e: self.preview())
        ttk.Button(self.buttons, text="Save and print", command=lambda: self.save(True)).pack(side="right")
        ttk.Button(self.buttons, text="Save", style="Primary.TButton", command=self.save).pack(side="right", padx=8)
        ttk.Button(self.buttons, text="Cancel", command=self.destroy).pack(side="right")
        self.open_docs = []
        if contact_id:
            self.contact.set(next((c[1] for c in self.contacts if c[0] == contact_id), ""))
            self.load()

    def contact_id(self):
        return next((c[0] for c in self.contacts if c[1] == self.contact.get()), None)

    def load(self):
        cid = self.contact_id()
        self.open_docs = sorted(self.books.invoices(self.inv_kind, "unpaid", cid), key=lambda r: (r["date"], r["id"]))
        if not self.amount.get():
            if self.invoice_first:
                bal = next((d["balance"] for d in self.open_docs if d["id"] == self.invoice_first), 0)
            else:
                bal = sum(d["balance"] for d in self.open_docs)
            self.amount.set(f"{bal:.2f}" if bal else "")
        self.preview()
        if self.invoice_first and self.table.tree.exists(str(self.invoice_first)):
            self.table.tree.selection_set(str(self.invoice_first))

    def allocations(self):
        try:
            left = num(self.amount.get())
        except ValueError:
            left = 0
        order = list(self.open_docs)
        sel = self.table.selected()
        if sel:
            order.sort(key=lambda d: 0 if str(d["id"]) == sel else 1)
        out = {}
        for d in order:
            a = min(left, round(d["balance"], 2))
            if a > 0:
                out[d["id"]] = round(a, 2)
                left -= a
        return out

    def preview(self):
        alloc = self.allocations()
        sel = self.table.selected()
        self.table.set_rows([[d["number"], d["date"], d["due_date"], money(d["total"]), money(d["balance"]),
                              money(alloc.get(d["id"], 0), True)] for d in self.open_docs],
                            ids=[d["id"] for d in self.open_docs])
        if sel and self.table.tree.exists(sel):
            self.table.tree.selection_set(sel)

    def save(self, print_after=False):
        try:
            if not valid_date(self.date.get()):
                raise AccError("Dates must be in the format YYYY-MM-DD.")
            bank = next((b[0] for b in self.banks if b[1] == self.bank.get()), None)
            pid = self.books.record_payment(self.kind, self.contact_id(), self.date.get(), bank,
                                            num(self.amount.get()), self.allocations(), self.method.get(),
                                            self.ref.get())
        except (AccError, ValueError) as exc:
            error(self, exc)
            return
        self.result = pid
        if print_after:
            from ..printing import print_payment
            print_payment(self.books, pid)
        self.destroy()


class ExpenseDialog(Dialog):
    def __init__(self, parent, books):
        super().__init__(parent, "Spend money (expense)", width=900)
        self.books = books
        hdr = _Header(self.body)
        hdr.pack(fill="x")
        self.date = tk.StringVar(value=date.today().isoformat())
        hdr.add("Date", ttk.Entry(hdr, textvariable=self.date, width=12))
        self.banks = [(a["id"], a["name"]) for a in books.bank_accounts()]
        self.bank = tk.StringVar(value=self.banks[0][1] if self.banks else "")
        hdr.add("Paid from", ttk.Combobox(hdr, textvariable=self.bank, values=[b[1] for b in self.banks],
                                          state="readonly", width=28))
        self.payee = tk.StringVar()
        hdr.add("Paid to (payee)", ttk.Entry(hdr, textvariable=self.payee, width=22))
        self.ref = tk.StringVar()
        hdr.add("Reference", ttk.Entry(hdr, textvariable=self.ref, width=14))
        self.lines = LinesEditor(self.body, books, "expense")
        self.lines.pack(fill="both", expand=True, pady=8)
        ttk.Button(self.buttons, text="Save", style="Primary.TButton", command=self.save).pack(side="right")
        ttk.Button(self.buttons, text="Cancel", command=self.destroy).pack(side="right", padx=8)

    def save(self):
        other = [l for l in self.lines.lines if self.lines.acct_types.get(l["account_id"]) != "expense"]
        if other and not confirm(self, "Some lines use an account that is not an expense account, so they will "
                                       "NOT appear under Expenses or reduce profit (for example buying equipment "
                                       "or paying VAT or a loan).\n\nSave anyway?"):
            return
        try:
            if not valid_date(self.date.get()):
                raise AccError("Dates must be in the format YYYY-MM-DD.")
            bank = next((b[0] for b in self.banks if b[1] == self.bank.get()), None)
            self.result = self.books.record_expense(self.date.get(), bank, self.lines.lines, self.payee.get(),
                                                    self.ref.get())
        except AccError as exc:
            error(self, exc)
            return
        self.destroy()


class JournalDialog(Dialog):
    def __init__(self, parent, books):
        super().__init__(parent, "New journal entry", width=900)
        self.books = books
        hdr = _Header(self.body)
        hdr.pack(fill="x")
        self.date = tk.StringVar(value=date.today().isoformat())
        hdr.add("Date", ttk.Entry(hdr, textvariable=self.date, width=12))
        self.ref = tk.StringVar()
        hdr.add("Reference", ttk.Entry(hdr, textvariable=self.ref, width=14))
        self.memo = tk.StringVar()
        hdr.add("Narration", ttk.Entry(hdr, textvariable=self.memo, width=50))
        self.lines = LinesEditor(self.body, books, "journal")
        self.lines.pack(fill="both", expand=True, pady=8)
        ttk.Button(self.buttons, text="Post journal", style="Primary.TButton", command=self.save).pack(side="right")
        ttk.Button(self.buttons, text="Cancel", command=self.destroy).pack(side="right", padx=8)

    def save(self):
        try:
            if not self.memo.get().strip():
                raise AccError("Enter a narration explaining the journal.")
            self.result = self.books.manual_journal(self.date.get(), self.memo.get(), self.lines.lines, self.ref.get())
        except AccError as exc:
            error(self, exc)
            return
        self.destroy()


class ReconcileDialog(Dialog):
    def __init__(self, parent, books, account_id):
        acc = books.one("SELECT * FROM accounts WHERE id=?", (account_id,))
        super().__init__(parent, f"Reconcile {acc['name']}", width=860)
        self.books, self.account_id = books, account_id
        hdr = _Header(self.body)
        hdr.pack(fill="x")
        self.sdate = tk.StringVar(value=date.today().isoformat())
        e = hdr.add("Statement date", ttk.Entry(hdr, textvariable=self.sdate, width=12))
        e.bind("<FocusOut>", lambda ev: self.load())
        self.sbal = tk.StringVar()
        e2 = hdr.add("Statement closing balance", ttk.Entry(hdr, textvariable=self.sbal, width=16))
        e2.bind("<KeyRelease>", lambda ev: self.update_sum())
        ttk.Button(hdr, text="Load", command=self.load).grid(row=1, column=hdr.col, pady=(2, 10))
        ttk.Label(self.body, text="Click lines that appear on the bank statement to tick them.",
                  style="CardMuted.TLabel").pack(anchor="w")
        self.table = Table(self.body, [("tick", "\u2713", 40, "center"), ("date", "Date", 90, "w"),
                                       ("ref", "Ref", 100, "w"), ("memo", "Details", 300, "w"),
                                       ("in", "Money in", 110, "e"), ("out", "Money out", 110, "e")], height=12)
        self.table.pack(fill="both", expand=True, pady=6)
        self.table.tree.bind("<ButtonRelease-1>", self.toggle)
        self.sum_lbl = ttk.Label(self.buttons, text="", style="Card.TLabel", font=f(11, "bold"))
        self.sum_lbl.pack(side="left")
        ttk.Button(self.buttons, text="Finish reconciliation", style="Primary.TButton",
                   command=self.finish).pack(side="right")
        ttk.Button(self.buttons, text="Cancel", command=self.destroy).pack(side="right", padx=8)
        self.ticked = set()
        self.lines = []
        self.load()

    def load(self):
        if not valid_date(self.sdate.get()):
            return
        self.lines = self.books.unreconciled_lines(self.account_id, self.sdate.get())
        self.render()

    def render(self):
        self.table.set_rows([["\u2713" if l["id"] in self.ticked else "", l["date"], l["ref"], l["memo"],
                              money(l["debit"], True), money(l["credit"], True)] for l in self.lines],
                            ids=[l["id"] for l in self.lines])
        self.update_sum()

    def toggle(self, _e):
        sel = self.table.selected()
        if not sel:
            return
        lid = int(sel)
        self.ticked.symmetric_difference_update({lid})
        self.render()
        self.table.tree.selection_set(sel)

    def cleared(self):
        return self.books.reconciled_balance(self.account_id) + sum(
            l["debit"] - l["credit"] for l in self.lines if l["id"] in self.ticked)

    def update_sum(self):
        try:
            sb = num(self.sbal.get())
        except ValueError:
            sb = 0
        diff = self.cleared() - sb
        self.sum_lbl.configure(text=f"Cleared balance {money(self.cleared())}    Difference {money(diff)}",
                               foreground=C.EMERALD if abs(diff) < 0.005 else C.DANGER)

    def finish(self):
        try:
            self.books.reconcile(self.account_id, self.sdate.get(), num(self.sbal.get()), list(self.ticked))
        except (AccError, ValueError) as exc:
            error(self, exc)
            return
        self.result = True
        self.destroy()
