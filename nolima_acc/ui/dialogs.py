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
    """kind: 'sale' | 'bill' | 'quote'; cash=True makes a cash sale (paid immediately)."""

    def __init__(self, parent, books, kind="sale", cash=False):
        titles = {"sale": "New invoice", "bill": "New supplier bill", "quote": "New quotation"}
        super().__init__(parent, "Cash sale" if cash else titles[kind], width=980)
        self.books, self.kind, self.cash = books, kind, cash
        sale_like = kind in ("sale", "quote")
        self.ckind = "customer" if sale_like else "supplier"
        hdr = _Header(self.body)
        hdr.pack(fill="x")
        self.contact = tk.StringVar()
        self.contact_cb = hdr.add("Customer" if sale_like else "Supplier",
                                  ttk.Combobox(hdr, textvariable=self.contact, state="readonly", width=30))
        ttk.Button(hdr, text="+ New", command=self.new_contact).grid(row=1, column=hdr.col, padx=(0, 16), pady=(2, 10))
        hdr.col += 1
        self.date = tk.StringVar(value=date.today().isoformat())
        hdr.add("Date", ttk.Entry(hdr, textvariable=self.date, width=12))
        self.due = tk.StringVar(value=(date.today() + timedelta(days=30)).isoformat())
        if not cash:
            hdr.add("Valid until" if kind == "quote" else "Due date", ttk.Entry(hdr, textvariable=self.due, width=12))
        self.ref = tk.StringVar()
        hdr.add("Reference" if sale_like else "Supplier invoice no.", ttk.Entry(hdr, textvariable=self.ref, width=16))
        self.banks = [(a["id"], a["name"]) for a in books.bank_accounts()]
        if cash:
            self.bank = tk.StringVar(value=self.banks[0][1] if self.banks else "")
            hdr.add("Paid into", ttk.Combobox(hdr, textvariable=self.bank, values=[b[1] for b in self.banks],
                                              state="readonly", width=26))
        opts = ttk.Frame(self.body, style="Card.TFrame")
        opts.pack(fill="x")
        self.levy_rate = books.levy_rate if sale_like else 0.0
        self.levy_on = tk.BooleanVar(value=self.levy_rate > 0)
        self.inc = tk.BooleanVar(value=False)  # prices are always before VAT and levy
        ttk.Label(opts, text="Prices are before VAT" + (" and levy" if self.levy_rate else "") +
                  "; VAT" + (" and levy are" if self.levy_rate else " is") + " calculated on the subtotal.",
                  style="CardMuted.TLabel").pack(side="left")
        if self.levy_rate:
            ttk.Checkbutton(opts, text=f"Charge tourism levy ({self.levy_rate:g}%)", variable=self.levy_on,
                            style="Card.TCheckbutton", command=self.update_totals).pack(side="left", padx=18)
        self.lines = LinesEditor(self.body, books, "sale" if sale_like else "bill")
        self.lines.pack(fill="both", expand=True, pady=8)
        self.lines.on_change = self.update_totals
        if kind == "bill":
            ttk.Label(self.body, text="Stock items bought go into Inventory. Their cost becomes an expense (cost of "
                                      "sales) when they are sold using the same item.", style="CardMuted.TLabel"
                      ).pack(anchor="w")
        self.memo = tk.StringVar()
        m = ttk.Frame(self.body, style="Card.TFrame")
        m.pack(fill="x", pady=(4, 0))
        ttk.Label(m, text="Notes", style="CardMuted.TLabel").pack(side="left")
        ttk.Entry(m, textvariable=self.memo).pack(side="left", fill="x", expand=True, padx=8)
        # withholding tax: typed in by hand, customer invoices only
        self.wht = tk.StringVar()
        if kind == "sale" and not cash:
            wf = ttk.Frame(self.body, style="Card.TFrame")
            wf.pack(fill="x", pady=(8, 0))
            ttk.Label(wf, text="Withholding tax deducted by customer (MWK)", style="CardMuted.TLabel").pack(side="left")
            e = ttk.Entry(wf, textvariable=self.wht, width=14)
            e.pack(side="left", padx=8)
            e.bind("<KeyRelease>", lambda ev: self.update_totals())
            ttk.Label(wf, text="Optional", style="CardMuted.TLabel").pack(side="left", padx=4)
        # part payment at the time of invoicing
        self.paid_now = tk.StringVar()
        if kind in ("sale", "bill") and not cash:
            pp = ttk.Frame(self.body, style="Card.TFrame")
            pp.pack(fill="x", pady=(8, 0))
            ttk.Label(pp, text="Part payment now (optional)" if kind == "sale" else "Amount paid now (optional)",
                      style="CardMuted.TLabel").pack(side="left")
            ttk.Entry(pp, textvariable=self.paid_now, width=14).pack(side="left", padx=8)
            self.pp_bank = tk.StringVar(value=self.banks[0][1] if self.banks else "")
            ttk.Combobox(pp, textvariable=self.pp_bank, values=[b[1] for b in self.banks], state="readonly",
                         width=26).pack(side="left", padx=4)
            self.pp_method = tk.StringVar(value="Cash")
            ttk.Combobox(pp, textvariable=self.pp_method, width=14,
                         values=["Cash", "Bank transfer", "Airtel Money", "TNM Mpamba", "Cheque", "Card"]
                         ).pack(side="left", padx=4)
            ttk.Label(self.body, text="Leave blank if nothing is paid yet. Any amount less than the total is a part "
                                      "payment; the rest stays as a balance due.", style="CardMuted.TLabel"
                      ).pack(anchor="w", pady=(2, 0))
        self.totals = ttk.Label(self.body, text="", style="Card.TLabel", font=f(11, "bold"))
        self.totals.pack(anchor="e", pady=(12, 0))
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
        if not self.lines.lines:
            self.totals.configure(text="Total MWK 0.00")
            return
        try:
            calc = self.books._calc_lines(self.lines.lines, self.inc.get(),
                                          self.levy_rate if self.levy_on.get() else 0.0)
        except AccError:
            return
        t = self.books.totals(calc)
        parts = []
        if t["discount"]:
            parts.append(f"Discount {money(t['discount'])}")
        parts += [f"Subtotal {money(t['subtotal'])}", f"VAT {money(t['vat'])}"]
        if t["levy"]:
            parts.append(f"Levy {money(t['levy'])}")
        parts.append(f"Total MWK {money(t['total'])}")
        try:
            w = num(self.wht.get()) if self.wht.get().strip() else 0
        except ValueError:
            w = 0
        if w:
            parts.append(f"Less WHT {money(w)}   Customer pays {money(t['total'] - w)}")
        self.totals.configure(text="    ".join(parts))

    def save(self, print_after=False):
        cid = next((c[0] for c in self.contacts if c[1] == self.contact.get()), None)
        try:
            if not valid_date(self.date.get()) or (not self.cash and not valid_date(self.due.get())):
                raise AccError("Dates must be in the format YYYY-MM-DD.")
            levy = bool(self.levy_on.get())
            if self.kind == "quote":
                doc_id = self.books.create_quote(cid, self.date.get(), self.lines.lines, self.due.get(),
                                                 self.memo.get(), self.ref.get(), False, levy)
            elif self.cash:
                bank = next((b[0] for b in self.banks if b[1] == self.bank.get()), None)
                doc_id = self.books.cash_sale(cid, self.date.get(), self.lines.lines, bank, method=self.bank.get(),
                                              reference=self.ref.get(), memo=self.memo.get(),
                                              prices_inc_vat=False, apply_levy=levy)
            else:
                paid = None
                if self.paid_now.get().strip():
                    amt = num(self.paid_now.get())
                    if amt < 0:
                        raise AccError("The amount paid now cannot be negative.")
                    bank = next((b[0] for b in self.banks if b[1] == self.pp_bank.get()), None)
                    paid = {"amount": amt, "account_id": bank, "method": self.pp_method.get(),
                            "reference": self.ref.get()}
                w = num(self.wht.get()) if self.wht.get().strip() else 0
                if w < 0:
                    raise AccError("Withholding tax cannot be negative.")
                doc_id = self.books.create_invoice(self.kind, cid, self.date.get(), self.lines.lines,
                                                   due_date=self.due.get(), memo=self.memo.get(),
                                                   reference=self.ref.get(), prices_inc_vat=False,
                                                   apply_levy=levy, paid_now=paid, wht=w)
        except (AccError, ValueError) as exc:
            error(self, exc)
            return
        self.result = doc_id
        if print_after:
            from .. import printing
            (printing.print_quote if self.kind == "quote" else printing.print_invoice)(self.books, doc_id)
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
        self.cash_lbl = ttk.Label(self.body, text="", style="Card.TLabel", font=f(10, "bold"))
        self.cash_lbl.pack(anchor="w")
        ttk.Label(self.body, text="Unpaid documents. Enter less than the balance for a part payment; it is applied to "
                                  "the selected document first, then oldest first.",
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

    def wht(self):
        return 0.0  # withholding tax is entered on customer invoices, not on payments

    def preview(self):
        try:
            settled = num(self.amount.get())
        except ValueError:
            settled = 0
        w = self.wht()
        word = "received" if self.kind == "receipt" else "paid"
        who = "withheld by the customer" if self.kind == "receipt" else "deducted and owed to MRA"
        self.cash_lbl.configure(text=f"Amount {word}: MWK {money(settled)}")
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
            w = self.wht()
            pid = self.books.record_payment(self.kind, self.contact_id(), self.date.get(), bank,
                                            round(num(self.amount.get()) - w, 2), self.allocations(),
                                            self.method.get(), self.ref.get(), wht=w)
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
