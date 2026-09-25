"""Nolima Licence Generator - FOR NOLIMA TECH CONSULTANTS ONLY. Never ship this to customers.

Keeps your private signing key and a register of customers and licences.
Issues new keys and renewal keys; tracks who is due for renewal and what they paid.

GUI:  python nolima_license_generator.py
CLI:  python nolima_license_generator.py issue --customer "Thunzi Executive Lodge" --machine ABCD-1234-ABCD-1234 \
          --plan business --cycle monthly --periods 1 --ref "MO-123"
      python nolima_license_generator.py due          (licences expiring within 14 days)
"""
from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from nolima_acc import licensing, plans  # noqa: E402

VAULT = Path(os.environ.get("NOLIMA_VAULT", Path.home() / "NolimaLicenseVault"))
KEY_FILE = VAULT / "nolima_signing_key.pem"
DB_FILE = VAULT / "licence_register.db"
PUBKEY_PY = HERE.parent / "nolima_acc" / "license_pubkey.py"

NAVY, EMERALD, BG = "#0F2A47", "#1B7F5C", "#F2F6F9"


# ---------------------------------------------------------------- keys
def ensure_keys() -> tuple[Ed25519PrivateKey, bool]:
    VAULT.mkdir(parents=True, exist_ok=True)
    created = False
    if not KEY_FILE.exists():
        priv = Ed25519PrivateKey.generate()
        KEY_FILE.write_bytes(priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                serialization.NoEncryption()))
        try:
            os.chmod(KEY_FILE, 0o600)
        except OSError:
            pass
        created = True
    priv = serialization.load_pem_private_key(KEY_FILE.read_bytes(), password=None)
    pub_hex = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    if PUBKEY_PY.exists() and pub_hex not in PUBKEY_PY.read_text():
        PUBKEY_PY.write_text("# Nolima licence verification key (Ed25519 public key, hex).\n"
                             "# Written by the Nolima Licence Generator. Rebuild the installer after it changes.\n"
                             f'PUBLIC_KEY_HEX = "{pub_hex}"\n')
    return priv, created


def public_hex(priv) -> str:
    return priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


# ---------------------------------------------------------------- register
def db():
    VAULT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_FILE)
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT, email TEXT,
        machine_id TEXT, plan TEXT DEFAULT 'business', cycle TEXT DEFAULT 'monthly', notes TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS licences (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id),
        plan TEXT, users INTEGER, issued TEXT, starts TEXT, expires TEXT, machine_id TEXT, key TEXT,
        cycle TEXT, periods INTEGER, amount REAL, payment_ref TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    return c


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    last = (date(y + (m // 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


def latest(conn, customer_id):
    return conn.execute("SELECT * FROM licences WHERE customer_id=? ORDER BY expires DESC, id DESC LIMIT 1",
                        (customer_id,)).fetchone()


def next_start(conn, customer_id, machine_id) -> date:
    last = latest(conn, customer_id)
    today = date.today()
    if last and last["machine_id"] == machine_id:
        return max(today, date.fromisoformat(last["expires"]) + timedelta(days=1))
    return today


def issue(conn, priv, customer_id, plan_key, cycle_key, periods=1, start: date | None = None, users=None,
          amount=None, payment_ref="", machine_id=None) -> tuple[str, dict]:
    cust = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
    machine_id = machine_id or cust["machine_id"]
    fp = licensing.parse_machine_id(machine_id)
    machine_id = licensing.format_machine_id(fp)
    plan = plans.PLANS[plan_key]
    months = plans.CYCLES[cycle_key]["months"] * periods
    start = start or next_start(conn, customer_id, machine_id)
    expires = add_months(start, months) - timedelta(days=1)
    users = plan["users"] if users is None else users
    serial = (conn.execute("SELECT MAX(id) FROM licences").fetchone()[0] or 0) + 1
    payload = licensing.build_payload(plan["code"], users, date.today(), expires, serial, fp)
    key = licensing.encode_key(payload, priv.sign(payload))
    # self-check with the public key
    os.environ["NOLIMA_PUBKEY_HEX"] = public_hex(priv)
    info = licensing.verify_key(key, fp)
    assert info.expires == expires
    if amount is None:
        amount = plans.cycle_price(plan_key, cycle_key) * periods
    conn.execute("INSERT INTO licences(id,customer_id,plan,users,issued,starts,expires,machine_id,key,cycle,periods,"
                 "amount,payment_ref) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (serial, customer_id, plan_key, users, date.today().isoformat(), start.isoformat(),
                  expires.isoformat(), machine_id, key, cycle_key, periods, amount, payment_ref))
    conn.execute("UPDATE customers SET machine_id=?, plan=?, cycle=? WHERE id=?", (machine_id, plan_key, cycle_key,
                                                                                  customer_id))
    conn.commit()
    return key, {"serial": serial, "starts": start, "expires": expires, "amount": amount, "plan": plan["name"],
                 "users": users, "machine_id": machine_id, "customer": cust["name"]}


def sign_update(installer: Path, version: str, notes: str = "", mandatory: bool = False, url: str = "",
                priv=None) -> tuple[Path, Path]:
    """Write update.json and update.json.sig next to the installer."""
    import hashlib
    import json
    priv = priv or ensure_keys()[0]
    installer = Path(installer)
    if not installer.exists():
        raise FileNotFoundError(installer)
    sha = hashlib.sha256(installer.read_bytes()).hexdigest()
    from nolima_acc import config as AC
    url = url or f"https://github.com/{AC.UPDATE_REPO}/releases/download/v{version}/{installer.name}"
    manifest = {"app": "NolimaAccounting", "version": version, "url": url, "sha256": sha,
                "size": installer.stat().st_size, "notes": notes, "mandatory": bool(mandatory),
                "published": datetime.now().strftime("%Y-%m-%d %H:%M")}
    body = json.dumps(manifest, indent=2).encode()
    m = installer.parent / "update.json"
    sig = installer.parent / "update.json.sig"
    m.write_bytes(body)
    sig.write_text(priv.sign(body).hex())
    return m, sig


def message_text(customer, meta, key):
    return (f"Dear {customer},\n\nThank you for your payment. Your Nolima Accounting licence key "
            f"({meta['plan']} package, {'unlimited' if not meta['users'] else meta['users']} users) is below. "
            f"It is valid until {meta['expires']:%d %B %Y}.\n\nIn Nolima Accounting go to Settings > Licence > "
            f"Enter renewal key, paste the key and click Apply.\n\n{key}\n\n"
            f"Nolima Tech Consultants \u00b7 099 025 2341 \u00b7 info@nolima.mw")


# ---------------------------------------------------------------- GUI
class GeneratorApp:
    def __init__(self, root):
        self.root = root
        self.priv, created = ensure_keys()
        self.conn = db()
        root.title("Nolima Licence Generator")
        root.geometry("1180x700")
        root.configure(bg=BG)
        s = ttk.Style(root)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure("Treeview", rowheight=26)
        s.configure("Treeview.Heading", background="#E8EEF3", foreground=NAVY)
        s.configure("Primary.TButton", background=EMERALD, foreground="white")
        s.map("Primary.TButton", background=[("active", "#22986E")])
        top = tk.Frame(root, bg=NAVY)
        top.pack(fill="x")
        tk.Label(top, text="Nolima Licence Generator", bg=NAVY, fg="white", font=("Segoe UI", 16, "bold"),
                 pady=12, padx=18).pack(side="left")
        tk.Label(top, text=f"Vault: {VAULT}", bg=NAVY, fg="#9FD4BF", padx=18).pack(side="right")
        bar = ttk.Frame(root, padding=(16, 12))
        bar.pack(fill="x")
        for text, cmd, prim in [("Issue / renew licence", self.issue_dialog, True), ("New customer", self.new_customer, False),
                                ("Edit customer", self.edit_customer, False), ("Licence history", self.history, False),
                                ("Export payments CSV", self.export, False), ("Public key", self.show_pub, False)]:
            ttk.Button(bar, text=text, command=cmd, style="Primary.TButton" if prim else "TButton").pack(side="left", padx=3)
        self.only_due = tk.BooleanVar()
        ttk.Checkbutton(bar, text="Only due within 14 days / expired", variable=self.only_due,
                        command=self.refresh).pack(side="right")
        cols = [("n", "Customer", 260), ("p", "Package", 100), ("c", "Cycle", 90), ("m", "Machine ID", 170),
                ("e", "Expires", 100), ("d", "Days left", 80), ("s", "Status", 110), ("ph", "Phone", 130)]
        fr = ttk.Frame(root, padding=(16, 0, 16, 8))
        fr.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(fr, columns=[c[0] for c in cols], show="headings")
        for k, h, w in cols:
            self.tree.heading(k, text=h)
            self.tree.column(k, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.tag_configure("due", foreground="#B54708")
        self.tree.tag_configure("expired", foreground="#B42318")
        self.tree.bind("<Double-1>", lambda e: self.issue_dialog())
        self.summary = ttk.Label(root, text="", padding=(16, 0, 16, 12))
        self.summary.pack(anchor="w")
        self.refresh()
        if created:
            messagebox.showinfo("Signing key created",
                                f"A new signing key was created in\n{VAULT}\n\nBACK UP THIS FOLDER. If the key is lost "
                                "you cannot renew existing customers.\n\nThe public key has been written to "
                                "nolima_acc/license_pubkey.py. Rebuild the Nolima Accounting installer now.",
                                parent=root)

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        today = date.today()
        mrr, due_n = 0.0, 0
        for c in self.conn.execute("SELECT * FROM customers ORDER BY name"):
            last = latest(self.conn, c["id"])
            exp = date.fromisoformat(last["expires"]) if last else None
            days = (exp - today).days if exp else None
            if days is None:
                status, tag = "No licence", ""
            elif days < 0:
                status, tag = "Expired", "expired"
            elif days <= plans.REMINDER_DAYS:
                status, tag = "Due for renewal", "due"
            else:
                status, tag = "Active", ""
            if days is not None and days >= 0:
                mrr += plans.PLANS.get(c["plan"], {"monthly": 0})["monthly"]
            if tag:
                due_n += 1
            if self.only_due.get() and not tag:
                continue
            self.tree.insert("", "end", iid=str(c["id"]), tags=(tag,), values=(
                c["name"], plans.PLANS.get(c["plan"], {"name": c["plan"].title()})["name"], plans.CYCLES[c["cycle"]]["name"].split(" ")[0],
                c["machine_id"] or "", exp.isoformat() if exp else "", "" if days is None else days, status,
                c["phone"] or ""))
        month_start = today.replace(day=1).isoformat()
        paid = self.conn.execute("SELECT SUM(amount) FROM licences WHERE issued>=?", (month_start,)).fetchone()[0] or 0
        self.summary.configure(text=f"Monthly recurring revenue (active licences): MWK {mrr:,.0f}     "
                                    f"Collected this month: MWK {paid:,.0f}     Due / expired: {due_n}")

    def _cid(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Select", "Select a customer first.", parent=self.root)
            return None
        return int(sel[0])

    def _customer_form(self, c=None):
        c = c or {}
        d = tk.Toplevel(self.root)
        d.title("Customer")
        d.transient(self.root)
        vals = {}
        for r, (k, label) in enumerate([("name", "Customer name"), ("phone", "Phone / WhatsApp"), ("email", "Email"),
                                        ("machine_id", "Machine ID (XXXX-XXXX-XXXX-XXXX)"), ("notes", "Notes")]):
            ttk.Label(d, text=label).grid(row=r, column=0, sticky="w", padx=12, pady=6)
            v = tk.StringVar(value=c.get(k) or "")
            ttk.Entry(d, textvariable=v, width=44).grid(row=r, column=1, padx=12, pady=6)
            vals[k] = v
        out = {}

        def save():
            if not vals["name"].get().strip():
                messagebox.showerror("Customer", "Name is required.", parent=d)
                return
            mid = vals["machine_id"].get().strip()
            if mid:
                try:
                    mid = licensing.format_machine_id(licensing.parse_machine_id(mid))
                except licensing.LicenseError as exc:
                    messagebox.showerror("Customer", str(exc), parent=d)
                    return
            out.update({k: v.get().strip() for k, v in vals.items()}, machine_id=mid)
            d.destroy()
        ttk.Button(d, text="Save", style="Primary.TButton", command=save).grid(row=6, column=1, sticky="e", padx=12,
                                                                               pady=12)
        d.grab_set()
        d.wait_window()
        return out or None

    def new_customer(self):
        v = self._customer_form()
        if v:
            self.conn.execute("INSERT INTO customers(name,phone,email,machine_id,notes) VALUES(?,?,?,?,?)",
                              (v["name"], v["phone"], v["email"], v["machine_id"], v["notes"]))
            self.conn.commit()
            self.refresh()

    def edit_customer(self):
        cid = self._cid()
        if not cid:
            return
        c = dict(self.conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone())
        v = self._customer_form(c)
        if v:
            self.conn.execute("UPDATE customers SET name=?,phone=?,email=?,machine_id=?,notes=? WHERE id=?",
                              (v["name"], v["phone"], v["email"], v["machine_id"], v["notes"], cid))
            self.conn.commit()
            self.refresh()

    def issue_dialog(self):
        cid = self._cid()
        if not cid:
            return
        c = self.conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
        d = tk.Toplevel(self.root)
        d.title(f"Issue licence \u2014 {c['name']}")
        d.transient(self.root)
        f = ttk.Frame(d, padding=16)
        f.pack(fill="both", expand=True)
        plan = tk.StringVar(value=plans.PLANS.get(c["plan"], plans.PLANS["business"])["name"])
        cycle = tk.StringVar(value=plans.CYCLES[c["cycle"]]["name"])
        periods = tk.StringVar(value="1")
        mid = tk.StringVar(value=c["machine_id"] or "")
        start = tk.StringVar()
        amount = tk.StringVar()
        ref = tk.StringVar()
        users = tk.StringVar()
        info = tk.StringVar()

        def pk():
            return next(k for k, p in plans.PLANS.items() if p["name"] == plan.get())

        def ck():
            return next(k for k, p in plans.CYCLES.items() if p["name"] == cycle.get())

        def recalc(*_):
            try:
                n = int(periods.get() or 1)
                amount.set(f"{plans.cycle_price(pk(), ck()) * n:,.2f}")
                users.set(str(plans.PLANS[pk()]["users"]))
                s = date.fromisoformat(start.get()) if start.get() else None
                if s:
                    e = add_months(s, plans.CYCLES[ck()]["months"] * n) - timedelta(days=1)
                    info.set(f"Licence will run {s:%d %b %Y} to {e:%d %b %Y}  (0 users = unlimited)")
            except Exception:
                pass
        try:
            start.set(next_start(self.conn, cid, licensing.format_machine_id(licensing.parse_machine_id(mid.get())))
                      .isoformat() if mid.get() else date.today().isoformat())
        except licensing.LicenseError:
            start.set(date.today().isoformat())
        rows = [("Machine ID", ttk.Entry(f, textvariable=mid, width=30)),
                ("Package", ttk.Combobox(f, textvariable=plan, values=[p["name"] for p in plans.PLANS.values()],
                                         state="readonly")),
                ("Billing cycle", ttk.Combobox(f, textvariable=cycle, values=[p["name"] for p in plans.CYCLES.values()],
                                               state="readonly")),
                ("Number of cycles paid", ttk.Spinbox(f, from_=1, to=24, textvariable=periods, width=6)),
                ("Start date (continues from last expiry)", ttk.Entry(f, textvariable=start, width=14)),
                ("Users", ttk.Entry(f, textvariable=users, width=8)),
                ("Amount received (MWK)", ttk.Entry(f, textvariable=amount, width=16)),
                ("Payment reference", ttk.Entry(f, textvariable=ref, width=30))]
        for r, (label, w) in enumerate(rows):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=5, padx=(0, 12))
            w.grid(row=r, column=1, sticky="w", pady=5)
            if isinstance(w, (ttk.Combobox, ttk.Spinbox)):
                w.bind("<<ComboboxSelected>>", recalc)
                w.bind("<KeyRelease>", recalc)
        periods.trace_add("write", recalc)
        start.trace_add("write", recalc)
        ttk.Label(f, textvariable=info, foreground=EMERALD).grid(row=8, column=0, columnspan=2, sticky="w", pady=6)
        out = tk.Text(f, height=9, width=90, font=("Consolas", 10), wrap="word")
        out.grid(row=10, column=0, columnspan=2, pady=8)
        recalc()
        state = {}

        def generate():
            try:
                key, meta = issue(self.conn, self.priv, cid, pk(), ck(), int(periods.get() or 1),
                                  date.fromisoformat(start.get()), int(users.get() or 0),
                                  float(amount.get().replace(",", "") or 0), ref.get(), mid.get())
            except Exception as exc:
                messagebox.showerror("Issue licence", str(exc), parent=d)
                return
            state.update(key=key, meta=meta)
            out.delete("1.0", "end")
            out.insert("1.0", message_text(c["name"], meta, key))
            self.root.clipboard_clear()
            self.root.clipboard_append(key)
            messagebox.showinfo("Licence issued", f"Licence #{meta['serial']:06d} valid until "
                                                  f"{meta['expires']:%d %B %Y}.\nThe key is copied to the clipboard; "
                                                  "the message below is ready for WhatsApp or email.", parent=d)
            self.refresh()

        def save_file():
            if not state:
                return
            p = filedialog.asksaveasfilename(parent=d, defaultextension=".txt",
                                             initialfile=f"Nolima licence {c['name']} {state['meta']['expires']}.txt")
            if p:
                Path(p).write_text(message_text(c["name"], state["meta"], state["key"]), encoding="utf-8")
        b = ttk.Frame(f)
        b.grid(row=9, column=0, columnspan=2, sticky="w")
        ttk.Button(b, text="Generate key", style="Primary.TButton", command=generate).pack(side="left")
        ttk.Button(b, text="Save message to file", command=save_file).pack(side="left", padx=6)
        d.grab_set()

    def history(self):
        cid = self._cid()
        if not cid:
            return
        d = tk.Toplevel(self.root)
        d.title("Licence history")
        cols = [("s", "No.", 60), ("p", "Package", 90), ("i", "Issued", 95), ("st", "Starts", 95), ("e", "Expires", 95),
                ("a", "Amount", 110), ("r", "Payment ref", 140), ("m", "Machine", 160)]
        t = ttk.Treeview(d, columns=[x[0] for x in cols], show="headings", height=14)
        for k, h, w in cols:
            t.heading(k, text=h)
            t.column(k, width=w)
        t.pack(fill="both", expand=True, padx=10, pady=10)
        keys = {}
        for l in self.conn.execute("SELECT * FROM licences WHERE customer_id=? ORDER BY id DESC", (cid,)):
            iid = t.insert("", "end", values=(f"{l['id']:06d}", plans.PLANS.get(l["plan"], {"name": l["plan"].title()})["name"], l["issued"],
                                              l["starts"], l["expires"], f"{l['amount']:,.2f}", l["payment_ref"],
                                              l["machine_id"]))
            keys[iid] = l["key"]

        def copy():
            sel = t.selection()
            if sel:
                self.root.clipboard_clear()
                self.root.clipboard_append(keys[sel[0]])
        ttk.Button(d, text="Copy selected key", command=copy).pack(pady=(0, 10))

    def export(self):
        p = filedialog.asksaveasfilename(parent=self.root, defaultextension=".csv",
                                         initialfile=f"Nolima licence payments {date.today()}.csv")
        if not p:
            return
        with open(p, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["Licence no", "Customer", "Package", "Cycle", "Periods", "Issued", "Starts", "Expires",
                        "Amount (MWK)", "Payment ref"])
            for r in self.conn.execute("SELECT l.*, c.name FROM licences l JOIN customers c ON c.id=l.customer_id "
                                       "ORDER BY l.id"):
                w.writerow([r["id"], r["name"], r["plan"], r["cycle"], r["periods"], r["issued"], r["starts"],
                            r["expires"], r["amount"], r["payment_ref"]])
        messagebox.showinfo("Export", f"Saved {p}", parent=self.root)

    def show_pub(self):
        messagebox.showinfo("Public key", f"{public_hex(self.priv)}\n\nThis goes in nolima_acc/license_pubkey.py "
                                          "(done automatically).", parent=self.root)


# ---------------------------------------------------------------- CLI
def cli(argv):
    # Windows consoles default to a code page that cannot print some characters
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Nolima Licence Generator")
    sub = ap.add_subparsers(dest="cmd")
    i = sub.add_parser("issue")
    i.add_argument("--customer", required=True)
    i.add_argument("--machine", required=True)
    i.add_argument("--plan", default="business", choices=list(plans.PLANS))
    i.add_argument("--cycle", default="monthly", choices=list(plans.CYCLES))
    i.add_argument("--periods", type=int, default=1)
    i.add_argument("--start")
    i.add_argument("--ref", default="")
    sub.add_parser("due")
    sub.add_parser("pubkey")
    sub.add_parser("init", help="create the signing key (if missing) and write the public key into the app")
    su = sub.add_parser("sign-update", help="sign an installer for remote update")
    su.add_argument("installer")
    su.add_argument("--version", required=True)
    su.add_argument("--notes", default="")
    su.add_argument("--notes-file")
    su.add_argument("--mandatory", action="store_true")
    su.add_argument("--url", default="")
    a = ap.parse_args(argv)
    priv, _ = ensure_keys()
    conn = db()
    if a.cmd == "issue":
        row = conn.execute("SELECT id FROM customers WHERE name=?", (a.customer,)).fetchone()
        cid = row["id"] if row else conn.execute("INSERT INTO customers(name, machine_id) VALUES(?,?)",
                                                 (a.customer, a.machine)).lastrowid
        conn.commit()
        key, meta = issue(conn, priv, cid, a.plan, a.cycle, a.periods,
                          date.fromisoformat(a.start) if a.start else None, payment_ref=a.ref, machine_id=a.machine)
        print(message_text(a.customer, meta, key))
    elif a.cmd == "due":
        for c in conn.execute("SELECT * FROM customers ORDER BY name"):
            last = latest(conn, c["id"])
            if last:
                days = (date.fromisoformat(last["expires"]) - date.today()).days
                if days <= plans.REMINDER_DAYS:
                    print(f"{c['name']:<35} {last['expires']}  {days:>4} days  {c['phone'] or ''}")
    elif a.cmd == "pubkey":
        print(public_hex(priv))
    elif a.cmd == "sign-update":
        notes = Path(a.notes_file).read_text(encoding="utf-8") if a.notes_file else a.notes
        m, sig = sign_update(Path(a.installer), a.version, notes, a.mandatory, a.url, priv)
        print(f"Signed: {m}\n        {sig}")
    elif a.cmd == "init":
        print(f"Signing key: {KEY_FILE}")
        print(f"Public key written to: {PUBKEY_PY}")
        print(public_hex(priv))
    else:
        ap.print_help()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cli(sys.argv[1:])
    else:
        root = tk.Tk()
        GeneratorApp(root)
        root.mainloop()
