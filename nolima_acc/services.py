"""Business logic for Nolima Accounting.

Every financial document posts a balanced double entry through post_entry().
The UI only talks to this module, so a network server can wrap it later
(the same pattern as Nolima Store's RPC layer).
"""
from __future__ import annotations

import csv
import hashlib
import os
import secrets
import shutil
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from . import coa_templates, db

ROLES = ["Administrator", "Accountant", "Cashier", "Viewer"]
# what each role may do
PERMS = {
    "Administrator": {"post", "journal", "setup", "users", "void", "reports", "backup"},
    "Accountant": {"post", "journal", "setup", "void", "reports", "backup"},
    "Cashier": {"post", "reports"},
    "Viewer": {"reports"},
}
EPS = 0.005


class AccError(Exception):
    """A user-facing validation error."""


def r2(x) -> float:
    return round(float(x or 0) + 0.0, 2)


def today() -> str:
    return date.today().isoformat()


def _hash(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()


class Books:
    def __init__(self, path, license_status=None):
        self.path = Path(path)
        self.conn = db.connect(self.path)
        self.user = None            # sqlite Row of logged-in user
        self._license = license_status  # callable -> LicenseStatus (or None in tests)

    # ------------------------------------------------------------ basics
    def q(self, sql, args=()):
        return self.conn.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        return self.conn.execute(sql, args).fetchone()

    def val(self, sql, args=(), default=None):
        row = self.conn.execute(sql, args).fetchone()
        return default if row is None or row[0] is None else row[0]

    def setting(self, key, default=None):
        return self.val("SELECT value FROM settings WHERE key=?", (key,), default)

    def set_setting(self, key, value):
        self.conn.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        self.conn.commit()

    @property
    def username(self):
        return self.user["username"] if self.user else "system"

    def audit(self, action, entity="", entity_id=None, details=""):
        self.conn.execute("INSERT INTO audit_log(username,action,entity,entity_id,details) VALUES(?,?,?,?,?)",
                          (self.username, action, entity, entity_id, details))

    def can(self, perm) -> bool:
        return bool(self.user) and perm in PERMS.get(self.user["role"], set())

    def require(self, perm):
        if self.user is not None and not self.can(perm):
            raise AccError(f"Your role ({self.user['role']}) is not allowed to do this.")

    def license(self):
        return self._license() if self._license else None

    def guard_write(self, perm="post"):
        st = self.license()
        if st is not None and not st.writable:
            raise AccError("Nolima Accounting is in read-only mode.\n\n" + st.message)
        self.require(perm)

    def has_module(self, module) -> bool:
        st = self.license()
        return True if st is None else st.has(module)

    def need_module(self, module):
        if not self.has_module(module):
            raise AccError("This feature is not included in your licence package. "
                           "Contact Nolima Tech Consultants to upgrade.")

    # ------------------------------------------------------------ setup
    def is_setup(self) -> bool:
        return self.setting("company_name") is not None

    def setup_company(self, name, industry, admin_user, admin_pw, admin_name="", address="", phone="",
                      email="", tpin="", vat_rate=16.5, fy_start_month=1, currency="MWK"):
        if self.is_setup():
            raise AccError("Company already set up.")
        if not name.strip():
            raise AccError("Company name is required.")
        for k, v in dict(company_name=name.strip(), industry=industry, address=address, phone=phone, email=email,
                         tpin=tpin, vat_rate=vat_rate, fy_start_month=fy_start_month, currency=currency,
                         lock_date="", inv_prefix="INV-", bill_prefix="BILL-", rcpt_prefix="RCT-",
                         pay_prefix="PAY-").items():
            self.set_setting(k, v)
        for code, nm, t, st in coa_templates.template(industry):
            self.conn.execute("INSERT INTO accounts(code,name,type,subtype,system) VALUES(?,?,?,?,?)",
                              (code, nm, t, st, 1 if st not in ("other", "fixed_asset") else 0))
        for dept in coa_templates.DEPARTMENTS.get(industry, []):
            self.conn.execute("INSERT INTO departments(name) VALUES(?)", (dept,))
        self.conn.commit()
        self.create_user(admin_user, admin_pw, "Administrator", admin_name, _bootstrap=True)
        self.audit("setup", "company", None, f"Company '{name}' created ({industry})")
        self.conn.commit()

    def company(self) -> dict:
        keys = ["company_name", "industry", "address", "phone", "email", "tpin", "vat_rate",
                "fy_start_month", "currency", "lock_date"]
        return {k: self.setting(k, "") for k in keys}

    def update_company(self, **kw):
        self.require("setup")
        for k, v in kw.items():
            self.set_setting(k, v)
        self.audit("update", "company", None, ", ".join(kw))
        self.conn.commit()

    @property
    def vat_rate(self) -> float:
        return float(self.setting("vat_rate", 16.5) or 0)

    # ------------------------------------------------------------ users
    def create_user(self, username, password, role, full_name="", _bootstrap=False):
        if not _bootstrap:
            self.require("users")
        if role not in ROLES:
            raise AccError("Unknown role.")
        if len(password) < 6:
            raise AccError("Password must be at least 6 characters.")
        if not username.strip():
            raise AccError("Username is required.")
        st = self.license()
        if st is not None and st.max_users:
            active = self.val("SELECT COUNT(*) FROM users WHERE active=1", default=0)
            if active >= st.max_users:
                raise AccError(f"Your licence allows {st.max_users} active user(s). "
                               "Deactivate a user or upgrade your package.")
        salt = secrets.token_hex(16)
        try:
            cur = self.conn.execute("INSERT INTO users(username,full_name,role,pw_hash,salt) VALUES(?,?,?,?,?)",
                                    (username.strip(), full_name, role, _hash(password, salt), salt))
        except sqlite3.IntegrityError:
            raise AccError("That username already exists.")
        self.audit("create", "user", cur.lastrowid, f"{username} ({role})")
        self.conn.commit()
        return cur.lastrowid

    def update_user(self, uid, role=None, full_name=None, active=None, password=None):
        self.require("users")
        u = self.one("SELECT * FROM users WHERE id=?", (uid,))
        if not u:
            raise AccError("User not found.")
        if active is not None and not active and u["role"] == "Administrator":
            admins = self.val("SELECT COUNT(*) FROM users WHERE role='Administrator' AND active=1")
            if admins <= 1:
                raise AccError("At least one active Administrator is required.")
        if active and not u["active"]:
            st = self.license()
            if st is not None and st.max_users:
                if self.val("SELECT COUNT(*) FROM users WHERE active=1") >= st.max_users:
                    raise AccError(f"Your licence allows {st.max_users} active user(s).")
        if role:
            self.conn.execute("UPDATE users SET role=? WHERE id=?", (role, uid))
        if full_name is not None:
            self.conn.execute("UPDATE users SET full_name=? WHERE id=?", (full_name, uid))
        if active is not None:
            self.conn.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, uid))
        if password:
            if len(password) < 6:
                raise AccError("Password must be at least 6 characters.")
            salt = secrets.token_hex(16)
            self.conn.execute("UPDATE users SET pw_hash=?, salt=? WHERE id=?", (_hash(password, salt), salt, uid))
        self.audit("update", "user", uid, u["username"])
        self.conn.commit()

    def change_own_password(self, old, new):
        if not self.user or _hash(old, self.user["salt"]) != self.user["pw_hash"]:
            raise AccError("Current password is incorrect.")
        if len(new) < 6:
            raise AccError("Password must be at least 6 characters.")
        salt = secrets.token_hex(16)
        self.conn.execute("UPDATE users SET pw_hash=?, salt=? WHERE id=?", (_hash(new, salt), salt, self.user["id"]))
        self.conn.commit()
        self.user = self.one("SELECT * FROM users WHERE id=?", (self.user["id"],))

    def login(self, username, password):
        u = self.one("SELECT * FROM users WHERE username=? AND active=1", (username.strip(),))
        if not u or _hash(password, u["salt"]) != u["pw_hash"]:
            raise AccError("Incorrect username or password.")
        self.user = u
        from .config import DEFAULT_ADMIN_PASSWORD
        self.using_default_password = password == DEFAULT_ADMIN_PASSWORD
        self.audit("login", "user", u["id"])
        self.conn.commit()
        return u

    def users(self):
        return self.q("SELECT id, username, full_name, role, active, created_at FROM users ORDER BY username")

    # ------------------------------------------------------------ accounts
    def accounts(self, types=None, subtypes=None, active_only=True):
        sql, args = "SELECT * FROM accounts WHERE 1=1", []
        if active_only:
            sql += " AND active=1"
        if types:
            sql += f" AND type IN ({','.join('?' * len(types))})"
            args += list(types)
        if subtypes:
            sql += f" AND subtype IN ({','.join('?' * len(subtypes))})"
            args += list(subtypes)
        return self.q(sql + " ORDER BY code", args)

    def account_by_subtype(self, subtype):
        row = self.one("SELECT * FROM accounts WHERE subtype=? AND active=1 ORDER BY code LIMIT 1", (subtype,))
        if not row:
            raise AccError(f"No '{subtype}' account found in the chart of accounts.")
        return row

    def save_account(self, code, name, type_, subtype="other", description="", account_id=None):
        self.guard_write("setup")
        if not code.strip() or not name.strip():
            raise AccError("Account code and name are required.")
        try:
            if account_id:
                acc = self.one("SELECT * FROM accounts WHERE id=?", (account_id,))
                if acc["system"] and (acc["type"] != type_ or acc["subtype"] != subtype):
                    raise AccError("The type of a system account cannot be changed.")
                self.conn.execute("UPDATE accounts SET code=?, name=?, type=?, subtype=?, description=? WHERE id=?",
                                  (code.strip(), name.strip(), type_, subtype, description, account_id))
                self.audit("update", "account", account_id, f"{code} {name}")
            else:
                cur = self.conn.execute(
                    "INSERT INTO accounts(code,name,type,subtype,description) VALUES(?,?,?,?,?)",
                    (code.strip(), name.strip(), type_, subtype, description))
                account_id = cur.lastrowid
                self.audit("create", "account", account_id, f"{code} {name}")
        except sqlite3.IntegrityError:
            raise AccError("An account with that code already exists.")
        self.conn.commit()
        return account_id

    def set_account_active(self, account_id, active):
        self.guard_write("setup")
        acc = self.one("SELECT * FROM accounts WHERE id=?", (account_id,))
        if acc["system"] and not active:
            raise AccError("System accounts cannot be deactivated.")
        if not active and abs(self.balance(account_id)) > EPS:
            raise AccError("Only accounts with a zero balance can be deactivated.")
        self.conn.execute("UPDATE accounts SET active=? WHERE id=?", (1 if active else 0, account_id))
        self.conn.commit()

    def balance(self, account_id, as_of=None, start=None, department_id=None) -> float:
        """Natural-sign balance: debit-positive for assets/expenses, credit-positive otherwise."""
        sql = ("SELECT COALESCE(SUM(l.debit - l.credit),0) FROM journal_lines l "
               "JOIN journal_entries e ON e.id=l.entry_id WHERE l.account_id=?")
        args = [account_id]
        if as_of:
            sql += " AND e.date<=?"
            args.append(as_of)
        if start:
            sql += " AND e.date>=?"
            args.append(start)
        if department_id:
            sql += " AND l.department_id=?"
            args.append(department_id)
        raw = self.val(sql, args, 0.0)
        t = self.val("SELECT type FROM accounts WHERE id=?", (account_id,))
        return r2(raw if t in ("asset", "expense") else -raw)

    # ------------------------------------------------------------ departments
    def departments(self, active_only=True):
        return self.q("SELECT * FROM departments" + (" WHERE active=1" if active_only else "") + " ORDER BY name")

    def save_department(self, name, dept_id=None, active=True):
        self.guard_write("setup")
        self.need_module("departments")
        try:
            if dept_id:
                self.conn.execute("UPDATE departments SET name=?, active=? WHERE id=?", (name, 1 if active else 0, dept_id))
            else:
                self.conn.execute("INSERT INTO departments(name) VALUES(?)", (name,))
        except sqlite3.IntegrityError:
            raise AccError("That department already exists.")
        self.conn.commit()

    # ------------------------------------------------------------ journal engine
    def check_period(self, d: str):
        lock = self.setting("lock_date", "")
        if lock and d <= lock:
            raise AccError(f"The period up to {lock} is closed. Choose a later date.")
        try:
            date.fromisoformat(d)
        except ValueError:
            raise AccError("Dates must be in the format YYYY-MM-DD.")

    def post_entry(self, d, memo, lines, source_type, source_id=None, ref="", commit=True):
        """lines: list of dicts {account_id, debit, credit, department_id?, description?}"""
        self.check_period(d)
        lines = [l for l in lines if r2(l.get("debit")) or r2(l.get("credit"))]
        if len(lines) < 2:
            raise AccError("A journal needs at least two lines.")
        dr = r2(sum(r2(l.get("debit")) for l in lines))
        cr = r2(sum(r2(l.get("credit")) for l in lines))
        if abs(dr - cr) > EPS:
            raise AccError(f"Debits ({dr:,.2f}) and credits ({cr:,.2f}) do not balance.")
        for l in lines:
            if r2(l.get("debit")) < 0 or r2(l.get("credit")) < 0:
                raise AccError("Journal amounts cannot be negative.")
        cur = self.conn.execute(
            "INSERT INTO journal_entries(date,ref,memo,source_type,source_id,created_by) VALUES(?,?,?,?,?,?)",
            (d, ref, memo, source_type, source_id, self.username))
        eid = cur.lastrowid
        for l in lines:
            self.conn.execute(
                "INSERT INTO journal_lines(entry_id,account_id,department_id,debit,credit,description) "
                "VALUES(?,?,?,?,?,?)",
                (eid, l["account_id"], l.get("department_id"), r2(l.get("debit")), r2(l.get("credit")),
                 l.get("description", "")))
        if commit:
            self.conn.commit()
        return eid

    def manual_journal(self, d, memo, lines, ref=""):
        self.guard_write("journal")
        eid = self.post_entry(d, memo, lines, "manual", ref=ref, commit=False)
        self.audit("post", "journal", eid, memo)
        self.conn.commit()
        return eid

    def reverse_entry(self, entry_id, d=None, memo=None, commit=True):
        e = self.one("SELECT * FROM journal_entries WHERE id=?", (entry_id,))
        lines = self.q("SELECT * FROM journal_lines WHERE entry_id=?", (entry_id,))
        d = d or today()
        rev = [{"account_id": l["account_id"], "department_id": l["department_id"],
                "debit": l["credit"], "credit": l["debit"], "description": "Reversal"} for l in lines]
        eid = self.post_entry(d, memo or f"Reversal of #{entry_id}: {e['memo']}", rev, "reversal",
                              source_id=entry_id, commit=False)
        self.conn.execute("UPDATE journal_entries SET reversal_of=? WHERE id=?", (entry_id, eid))
        if commit:
            self.conn.commit()
        return eid

    def reverse_manual_journal(self, entry_id):
        self.guard_write("void")
        e = self.one("SELECT * FROM journal_entries WHERE id=?", (entry_id,))
        if not e or e["source_type"] != "manual":
            raise AccError("Only manual journals can be reversed here. Void the source document instead.")
        if self.one("SELECT 1 FROM journal_entries WHERE reversal_of=?", (entry_id,)):
            raise AccError("This journal has already been reversed.")
        eid = self.reverse_entry(entry_id, commit=False)
        self.audit("reverse", "journal", entry_id)
        self.conn.commit()
        return eid

    def journals(self, start=None, end=None, source_type=None, limit=500):
        sql = ("SELECT e.*, (SELECT SUM(debit) FROM journal_lines WHERE entry_id=e.id) AS amount "
               "FROM journal_entries e WHERE 1=1")
        args = []
        if start:
            sql += " AND date>=?"; args.append(start)
        if end:
            sql += " AND date<=?"; args.append(end)
        if source_type:
            sql += " AND source_type=?"; args.append(source_type)
        return self.q(sql + " ORDER BY date DESC, id DESC LIMIT ?", args + [limit])

    def entry_lines(self, entry_id):
        return self.q("SELECT l.*, a.code, a.name AS account, d.name AS department FROM journal_lines l "
                      "JOIN accounts a ON a.id=l.account_id LEFT JOIN departments d ON d.id=l.department_id "
                      "WHERE entry_id=? ORDER BY l.id", (entry_id,))

    # ------------------------------------------------------------ contacts
    def contacts(self, kind, active_only=True, search=""):
        sql, args = "SELECT * FROM contacts WHERE kind=?", [kind]
        if active_only:
            sql += " AND active=1"
        if search:
            sql += " AND (name LIKE ? OR phone LIKE ? OR email LIKE ?)"
            args += [f"%{search}%"] * 3
        return self.q(sql + " ORDER BY name", args)

    def save_contact(self, kind, name, phone="", email="", address="", tpin="", contact_id=None, active=True):
        self.guard_write("post")
        if kind == "supplier":
            self.need_module("purchases")
        if not name.strip():
            raise AccError("Name is required.")
        if contact_id:
            self.conn.execute("UPDATE contacts SET name=?,phone=?,email=?,address=?,tpin=?,active=? WHERE id=?",
                              (name.strip(), phone, email, address, tpin, 1 if active else 0, contact_id))
            self.audit("update", kind, contact_id, name)
        else:
            contact_id = self.conn.execute(
                "INSERT INTO contacts(kind,name,phone,email,address,tpin) VALUES(?,?,?,?,?,?)",
                (kind, name.strip(), phone, email, address, tpin)).lastrowid
            self.audit("create", kind, contact_id, name)
        self.conn.commit()
        return contact_id

    def contact_balance(self, contact_id):
        kind = self.val("SELECT kind FROM contacts WHERE id=?", (contact_id,))
        k = "sale" if kind == "customer" else "bill"
        return r2(self.val("SELECT SUM(total-amount_paid) FROM invoices WHERE contact_id=? AND kind=? "
                           "AND status IN ('open','partial')", (contact_id, k), 0))

    # ------------------------------------------------------------ items / inventory
    def items(self, active_only=True, search=""):
        sql, args = "SELECT * FROM items WHERE 1=1", []
        if active_only:
            sql += " AND active=1"
        if search:
            sql += " AND (name LIKE ? OR code LIKE ?)"
            args += [f"%{search}%"] * 2
        return self.q(sql + " ORDER BY name", args)

    def save_item(self, name, kind="service", code="", unit="each", sale_price=0, cost_price=0,
                  income_account_id=None, expense_account_id=None, vatable=True, reorder_level=0,
                  item_id=None, active=True):
        self.guard_write("setup")
        if kind == "stock":
            self.need_module("inventory")
        if not name.strip():
            raise AccError("Item name is required.")
        code = code.strip() or None
        try:
            if item_id:
                self.conn.execute(
                    "UPDATE items SET name=?,kind=?,code=?,unit=?,sale_price=?,cost_price=?,income_account_id=?,"
                    "expense_account_id=?,vatable=?,reorder_level=?,active=? WHERE id=?",
                    (name, kind, code, unit, r2(sale_price), r2(cost_price), income_account_id, expense_account_id,
                     1 if vatable else 0, reorder_level, 1 if active else 0, item_id))
            else:
                item_id = self.conn.execute(
                    "INSERT INTO items(name,kind,code,unit,sale_price,cost_price,income_account_id,"
                    "expense_account_id,vatable,reorder_level) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (name, kind, code, unit, r2(sale_price), r2(cost_price), income_account_id, expense_account_id,
                     1 if vatable else 0, reorder_level)).lastrowid
        except sqlite3.IntegrityError:
            raise AccError("An item with that code already exists.")
        self.audit("save", "item", item_id, name)
        self.conn.commit()
        return item_id

    def adjust_stock(self, item_id, qty_change, d=None, memo="Stock adjustment", unit_cost=None):
        """Positive = found / opening stock, negative = loss / write-off."""
        self.guard_write("journal")
        self.need_module("inventory")
        d = d or today()
        it = self.one("SELECT * FROM items WHERE id=?", (item_id,))
        if not it or it["kind"] != "stock":
            raise AccError("Choose a stock item.")
        qty_change = float(qty_change)
        cost = r2(unit_cost if unit_cost is not None else it["cost_price"])
        value = r2(abs(qty_change) * cost)
        inv = self.account_by_subtype("inventory")["id"]
        other = self.account_by_subtype("opening")["id"] if qty_change > 0 else \
            self.one("SELECT id FROM accounts WHERE subtype='cogs'")["id"]
        if qty_change < 0 and it["qty_on_hand"] + qty_change < -EPS:
            raise AccError("Not enough stock on hand for this adjustment.")
        lines = ([{"account_id": inv, "debit": value}, {"account_id": other, "credit": value}] if qty_change > 0
                 else [{"account_id": other, "debit": value}, {"account_id": inv, "credit": value}])
        eid = self.post_entry(d, f"{memo}: {it['name']}", lines, "stock_adjust", item_id, commit=False) if value else None
        if qty_change > 0:
            self._receive_stock(it, qty_change, cost)
        else:
            self.conn.execute("UPDATE items SET qty_on_hand=qty_on_hand+? WHERE id=?", (qty_change, item_id))
        self.conn.execute("INSERT INTO stock_moves(item_id,date,qty,unit_cost,source_type,source_id,memo) "
                          "VALUES(?,?,?,?,?,?,?)", (item_id, d, qty_change, cost, "adjust", eid, memo))
        self.audit("adjust", "item", item_id, f"{qty_change:+g}")
        self.conn.commit()

    def _receive_stock(self, it, qty, cost):
        old_q, old_c = float(it["qty_on_hand"] or 0), float(it["cost_price"] or 0)
        new_q = old_q + qty
        avg = r2(((max(old_q, 0) * old_c) + qty * cost) / new_q) if new_q > 0 else cost
        self.conn.execute("UPDATE items SET qty_on_hand=?, cost_price=? WHERE id=?", (new_q, avg, it["id"]))

    # ------------------------------------------------------------ numbering
    def next_number(self, kind):
        prefix = {"sale": self.setting("inv_prefix", "INV-"), "bill": self.setting("bill_prefix", "BILL-"),
                  "receipt": self.setting("rcpt_prefix", "RCT-"), "payment": self.setting("pay_prefix", "PAY-")}[kind]
        table = "invoices" if kind in ("sale", "bill") else "payments"
        n = self.val(f"SELECT COUNT(*) FROM {table} WHERE kind=?", (kind,), 0) + 1
        while self.one(f"SELECT 1 FROM {table} WHERE kind=? AND number=?", (kind, f"{prefix}{n:05d}")):
            n += 1
        return f"{prefix}{n:05d}"

    # ------------------------------------------------------------ invoices & bills
    def _calc_lines(self, lines, prices_inc_vat=False):
        out = []
        for l in lines:
            qty = float(l.get("qty") or 0)
            price = float(l.get("unit_price") or 0)
            rate = float(l.get("vat_rate") or 0)
            gross_or_net = r2(qty * price)
            if prices_inc_vat and rate:
                net = r2(gross_or_net / (1 + rate / 100))
                vat = r2(gross_or_net - net)
            else:
                net = gross_or_net
                vat = r2(net * rate / 100)
            if qty <= 0:
                raise AccError("Quantities must be greater than zero.")
            if not l.get("account_id") and not l.get("item_id"):
                raise AccError("Each line needs an item or an account.")
            out.append(dict(l, qty=qty, unit_price=price, vat_rate=rate, net=net, vat=vat))
        if not out:
            raise AccError("Add at least one line.")
        return out

    def create_invoice(self, kind, contact_id, d, lines, due_date=None, memo="", reference="",
                       prices_inc_vat=False, number=None):
        """kind 'sale' (customer invoice) or 'bill' (supplier bill).
        lines: {item_id?, account_id?, description, qty, unit_price, vat_rate, department_id?}"""
        self.guard_write("post")
        if kind == "bill":
            self.need_module("purchases")
        if not contact_id:
            raise AccError("Choose a customer." if kind == "sale" else "Choose a supplier.")
        self.check_period(d)
        lines = self._calc_lines(lines, prices_inc_vat)
        if any(l.get("department_id") for l in lines):
            self.need_module("departments")
        number = number or self.next_number(kind)
        subtotal, vat = r2(sum(l["net"] for l in lines)), r2(sum(l["vat"] for l in lines))
        total = r2(subtotal + vat)
        due_date = due_date or (date.fromisoformat(d) + timedelta(days=30)).isoformat()
        try:
            inv_id = self.conn.execute(
                "INSERT INTO invoices(kind,number,contact_id,date,due_date,subtotal,vat,total,memo,reference,created_by) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (kind, number, contact_id, d, due_date, subtotal, vat, total, memo, reference, self.username)).lastrowid
        except sqlite3.IntegrityError:
            raise AccError(f"Number {number} is already used.")
        cname = self.val("SELECT name FROM contacts WHERE id=?", (contact_id,))
        je = []
        if kind == "sale":
            ar = self.account_by_subtype("receivable")["id"]
            je.append({"account_id": ar, "debit": total, "description": f"{number} {cname}"})
        else:
            ap = self.account_by_subtype("payable")["id"]
            je.append({"account_id": ap, "credit": total, "description": f"{number} {cname}"})
        for l in lines:
            item = self.one("SELECT * FROM items WHERE id=?", (l["item_id"],)) if l.get("item_id") else None
            if item and item["kind"] == "stock":
                self.need_module("inventory")
            if kind == "sale":
                acc = l.get("account_id") or (item["income_account_id"] if item else None) or \
                    self.one("SELECT id FROM accounts WHERE type='income' AND active=1 ORDER BY code")["id"]
            else:
                if item and item["kind"] == "stock":
                    acc = self.account_by_subtype("inventory")["id"]
                else:
                    acc = l.get("account_id") or (item["expense_account_id"] if item else None) or \
                        self.one("SELECT id FROM accounts WHERE code='6900'")["id"]
            unit_cost = 0.0
            if item and item["kind"] == "stock":
                if kind == "sale":
                    if item["qty_on_hand"] + EPS < l["qty"]:
                        raise AccError(f"Only {item['qty_on_hand']:g} {item['unit']} of {item['name']} in stock.")
                    unit_cost = float(item["cost_price"] or 0)
                else:
                    unit_cost = r2(l["net"] / l["qty"])
            self.conn.execute(
                "INSERT INTO invoice_lines(invoice_id,item_id,description,qty,unit_price,vat_rate,account_id,"
                "department_id,net,vat,unit_cost) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (inv_id, l.get("item_id"), l.get("description") or (item["name"] if item else ""), l["qty"],
                 l["unit_price"], l["vat_rate"], acc, l.get("department_id"), l["net"], l["vat"], unit_cost))
            side = "credit" if kind == "sale" else "debit"
            je.append({"account_id": acc, side: l["net"], "department_id": l.get("department_id"),
                       "description": l.get("description", "")})
            if item and item["kind"] == "stock":
                cost_val = r2(unit_cost * l["qty"])
                if kind == "sale":
                    if cost_val:
                        je.append({"account_id": item["expense_account_id"] or self.account_by_subtype("cogs")["id"],
                                   "debit": cost_val, "department_id": l.get("department_id"),
                                   "description": f"Cost of {item['name']}"})
                        je.append({"account_id": self.account_by_subtype("inventory")["id"], "credit": cost_val})
                    self.conn.execute("UPDATE items SET qty_on_hand=qty_on_hand-? WHERE id=?", (l["qty"], item["id"]))
                    self.conn.execute("INSERT INTO stock_moves(item_id,date,qty,unit_cost,source_type,source_id) "
                                      "VALUES(?,?,?,?,?,?)", (item["id"], d, -l["qty"], unit_cost, "sale", inv_id))
                else:
                    self._receive_stock(item, l["qty"], unit_cost)
                    self.conn.execute("INSERT INTO stock_moves(item_id,date,qty,unit_cost,source_type,source_id) "
                                      "VALUES(?,?,?,?,?,?)", (item["id"], d, l["qty"], unit_cost, "bill", inv_id))
        if vat:
            if kind == "sale":
                je.append({"account_id": self.account_by_subtype("vat_output")["id"], "credit": vat,
                           "description": f"VAT {number}"})
            else:
                je.append({"account_id": self.account_by_subtype("vat_input")["id"], "debit": vat,
                           "description": f"VAT {number}"})
        eid = self.post_entry(d, f"{'Invoice' if kind == 'sale' else 'Bill'} {number} - {cname}", je,
                              "invoice" if kind == "sale" else "bill", inv_id, ref=number, commit=False)
        self.conn.execute("UPDATE invoices SET entry_id=? WHERE id=?", (eid, inv_id))
        self.audit("create", "invoice" if kind == "sale" else "bill", inv_id, f"{number} {total:,.2f}")
        self.conn.commit()
        return inv_id

    def invoice(self, inv_id):
        return self.one("SELECT i.*, c.name AS contact, c.address, c.phone, c.email, c.tpin AS contact_tpin "
                        "FROM invoices i JOIN contacts c ON c.id=i.contact_id WHERE i.id=?", (inv_id,))

    def invoice_lines(self, inv_id):
        return self.q("SELECT l.*, d.name AS department FROM invoice_lines l "
                      "LEFT JOIN departments d ON d.id=l.department_id WHERE invoice_id=? ORDER BY l.id", (inv_id,))

    def invoices(self, kind, status=None, contact_id=None, search="", start=None, end=None):
        sql = ("SELECT i.*, c.name AS contact, (i.total-i.amount_paid) AS balance FROM invoices i "
               "JOIN contacts c ON c.id=i.contact_id WHERE i.kind=?")
        args = [kind]
        if status == "unpaid":
            sql += " AND i.status IN ('open','partial')"
        elif status:
            sql += " AND i.status=?"; args.append(status)
        if contact_id:
            sql += " AND i.contact_id=?"; args.append(contact_id)
        if search:
            sql += " AND (i.number LIKE ? OR c.name LIKE ? OR i.reference LIKE ?)"; args += [f"%{search}%"] * 3
        if start:
            sql += " AND i.date>=?"; args.append(start)
        if end:
            sql += " AND i.date<=?"; args.append(end)
        return self.q(sql + " ORDER BY i.date DESC, i.id DESC", args)

    def void_invoice(self, inv_id, reason=""):
        self.guard_write("void")
        inv = self.one("SELECT * FROM invoices WHERE id=?", (inv_id,))
        if not inv or inv["status"] == "void":
            raise AccError("Document not found or already void.")
        if inv["amount_paid"] > EPS:
            raise AccError("Remove the payments allocated to this document before voiding it.")
        d = max(today(), inv["date"])
        self.reverse_entry(inv["entry_id"], d, f"Void {inv['number']}: {reason}", commit=False)
        for l in self.invoice_lines(inv_id):
            if l["item_id"]:
                it = self.one("SELECT * FROM items WHERE id=?", (l["item_id"],))
                if it and it["kind"] == "stock":
                    sign = 1 if inv["kind"] == "sale" else -1
                    self.conn.execute("UPDATE items SET qty_on_hand=qty_on_hand+? WHERE id=?",
                                      (sign * l["qty"], it["id"]))
                    self.conn.execute("INSERT INTO stock_moves(item_id,date,qty,unit_cost,source_type,source_id,memo) "
                                      "VALUES(?,?,?,?,?,?,?)",
                                      (it["id"], d, sign * l["qty"], l["unit_cost"], "void", inv_id, inv["number"]))
        self.conn.execute("UPDATE invoices SET status='void' WHERE id=?", (inv_id,))
        self.audit("void", inv["kind"], inv_id, f"{inv['number']} {reason}")
        self.conn.commit()

    # ------------------------------------------------------------ receipts & payments
    def record_payment(self, kind, contact_id, d, account_id, amount, allocations=None, method="",
                       reference="", memo=""):
        """kind 'receipt' (from customer) or 'payment' (to supplier).
        allocations: {invoice_id: amount}. Unallocated money stays on account (credit)."""
        self.guard_write("post")
        if kind == "payment":
            self.need_module("purchases")
        amount = r2(amount)
        if amount <= 0:
            raise AccError("Amount must be greater than zero.")
        if not account_id:
            raise AccError("Choose the bank, cash or mobile money account.")
        allocations = {k: r2(v) for k, v in (allocations or {}).items() if r2(v) > 0}
        if r2(sum(allocations.values())) - amount > EPS:
            raise AccError("Allocated amounts exceed the payment amount.")
        inv_kind = "sale" if kind == "receipt" else "bill"
        for inv_id, amt in allocations.items():
            inv = self.one("SELECT * FROM invoices WHERE id=?", (inv_id,))
            if not inv or inv["kind"] != inv_kind or inv["contact_id"] != contact_id or inv["status"] == "void":
                raise AccError("Allocation refers to an invalid document.")
            if amt - r2(inv["total"] - inv["amount_paid"]) > EPS:
                raise AccError(f"{inv['number']} has only {inv['total'] - inv['amount_paid']:,.2f} outstanding.")
        number = self.next_number(kind)
        pid = self.conn.execute(
            "INSERT INTO payments(kind,number,contact_id,date,account_id,amount,method,reference,memo,created_by) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (kind, number, contact_id, d, account_id, amount, method, reference, memo, self.username)).lastrowid
        cname = self.val("SELECT name FROM contacts WHERE id=?", (contact_id,))
        if kind == "receipt":
            ctrl = self.account_by_subtype("receivable")["id"]
            lines = [{"account_id": account_id, "debit": amount, "description": f"{number} {cname}"},
                     {"account_id": ctrl, "credit": amount, "description": f"{number} {cname}"}]
        else:
            ctrl = self.account_by_subtype("payable")["id"]
            lines = [{"account_id": ctrl, "debit": amount, "description": f"{number} {cname}"},
                     {"account_id": account_id, "credit": amount, "description": f"{number} {cname}"}]
        eid = self.post_entry(d, f"{'Receipt' if kind == 'receipt' else 'Payment'} {number} - {cname}", lines,
                              kind, pid, ref=number, commit=False)
        self.conn.execute("UPDATE payments SET entry_id=? WHERE id=?", (eid, pid))
        for inv_id, amt in allocations.items():
            self._allocate(pid, inv_id, amt)
        self.audit("create", kind, pid, f"{number} {amount:,.2f}")
        self.conn.commit()
        return pid

    def _allocate(self, pid, inv_id, amt):
        self.conn.execute("INSERT INTO allocations(payment_id,invoice_id,amount) VALUES(?,?,?)", (pid, inv_id, amt))
        self.conn.execute("UPDATE invoices SET amount_paid=amount_paid+? WHERE id=?", (amt, inv_id))
        self._refresh_status(inv_id)

    def _refresh_status(self, inv_id):
        inv = self.one("SELECT * FROM invoices WHERE id=?", (inv_id,))
        if inv["status"] == "void":
            return
        bal = r2(inv["total"] - inv["amount_paid"])
        st = "paid" if bal <= EPS else ("partial" if inv["amount_paid"] > EPS else "open")
        self.conn.execute("UPDATE invoices SET status=? WHERE id=?", (st, inv_id))

    def unallocated(self, payment_id):
        p = self.one("SELECT * FROM payments WHERE id=?", (payment_id,))
        used = self.val("SELECT SUM(amount) FROM allocations WHERE payment_id=?", (payment_id,), 0)
        return r2(p["amount"] - used)

    def allocate_credit(self, payment_id, inv_id, amount):
        self.guard_write("post")
        if r2(amount) - self.unallocated(payment_id) > EPS:
            raise AccError("Amount exceeds the unallocated balance of this payment.")
        self._allocate(payment_id, inv_id, r2(amount))
        self.conn.commit()

    def void_payment(self, payment_id, reason=""):
        self.guard_write("void")
        p = self.one("SELECT * FROM payments WHERE id=?", (payment_id,))
        if not p or p["status"] == "void":
            raise AccError("Payment not found or already void.")
        if self.one("SELECT 1 FROM journal_lines WHERE entry_id=? AND rec_id IS NOT NULL", (p["entry_id"],)):
            raise AccError("This payment is part of a bank reconciliation and cannot be voided.")
        self.reverse_entry(p["entry_id"], max(today(), p["date"]), f"Void {p['number']}: {reason}", commit=False)
        for a in self.q("SELECT * FROM allocations WHERE payment_id=?", (payment_id,)):
            self.conn.execute("UPDATE invoices SET amount_paid=amount_paid-? WHERE id=?", (a["amount"], a["invoice_id"]))
            self._refresh_status(a["invoice_id"])
        self.conn.execute("DELETE FROM allocations WHERE payment_id=?", (payment_id,))
        self.conn.execute("UPDATE payments SET status='void' WHERE id=?", (payment_id,))
        self.audit("void", p["kind"], payment_id, reason)
        self.conn.commit()

    def payments(self, kind, contact_id=None, search=""):
        sql = ("SELECT p.*, c.name AS contact, a.name AS account FROM payments p JOIN contacts c ON c.id=p.contact_id "
               "JOIN accounts a ON a.id=p.account_id WHERE p.kind=?")
        args = [kind]
        if contact_id:
            sql += " AND p.contact_id=?"; args.append(contact_id)
        if search:
            sql += " AND (p.number LIKE ? OR c.name LIKE ? OR p.reference LIKE ?)"; args += [f"%{search}%"] * 3
        return self.q(sql + " ORDER BY p.date DESC, p.id DESC", args)

    def cash_sale(self, contact_id, d, lines, account_id, method="Cash", reference="", memo="", prices_inc_vat=True):
        inv_id = self.create_invoice("sale", contact_id, d, lines, due_date=d, memo=memo, reference=reference,
                                     prices_inc_vat=prices_inc_vat)
        total = self.val("SELECT total FROM invoices WHERE id=?", (inv_id,))
        self.record_payment("receipt", contact_id, d, account_id, total, {inv_id: total}, method, reference, memo)
        return inv_id

    # ------------------------------------------------------------ expenses & banking
    def record_expense(self, d, bank_account_id, lines, payee="", reference="", memo="", vat_inclusive=True):
        """Direct spend from a bank/cash account. lines: {account_id, amount, vat_rate, department_id, description}"""
        self.guard_write("post")
        je, total, vat_total = [], 0.0, 0.0
        for l in lines:
            amt, rate = r2(l.get("amount")), float(l.get("vat_rate") or 0)
            if amt <= 0:
                continue
            if rate:
                net = r2(amt / (1 + rate / 100)) if vat_inclusive else amt
                vat = r2(amt - net) if vat_inclusive else r2(amt * rate / 100)
            else:
                net, vat = amt, 0.0
            if l.get("department_id"):
                self.need_module("departments")
            je.append({"account_id": l["account_id"], "debit": net, "department_id": l.get("department_id"),
                       "description": l.get("description") or payee})
            total += net + vat
            vat_total += vat
        if not je:
            raise AccError("Enter at least one expense line.")
        if vat_total:
            je.append({"account_id": self.account_by_subtype("vat_input")["id"], "debit": r2(vat_total),
                       "description": "VAT on expense"})
        je.append({"account_id": bank_account_id, "credit": r2(total), "description": payee})
        eid = self.post_entry(d, f"Expense - {payee}" + (f" ({memo})" if memo else ""), je, "expense", ref=reference,
                              commit=False)
        self.audit("create", "expense", eid, f"{payee} {total:,.2f}")
        self.conn.commit()
        return eid

    def record_other_receipt(self, d, bank_account_id, income_account_id, amount, payer="", reference="", memo=""):
        self.guard_write("post")
        amount = r2(amount)
        eid = self.post_entry(d, f"Money received - {payer}" + (f" ({memo})" if memo else ""),
                              [{"account_id": bank_account_id, "debit": amount, "description": payer},
                               {"account_id": income_account_id, "credit": amount, "description": memo}],
                              "other_receipt", ref=reference, commit=False)
        self.audit("create", "other_receipt", eid, f"{payer} {amount:,.2f}")
        self.conn.commit()
        return eid

    def transfer(self, d, from_id, to_id, amount, memo="", reference=""):
        self.guard_write("post")
        if from_id == to_id:
            raise AccError("Choose two different accounts.")
        amount = r2(amount)
        if amount <= 0:
            raise AccError("Amount must be greater than zero.")
        eid = self.post_entry(d, memo or "Transfer", [{"account_id": to_id, "debit": amount},
                                                      {"account_id": from_id, "credit": amount}],
                              "transfer", ref=reference, commit=False)
        self.audit("create", "transfer", eid, f"{amount:,.2f}")
        self.conn.commit()
        return eid

    def bank_accounts(self):
        return self.accounts(subtypes=["bank", "cash"])

    # ------------------------------------------------------------ reconciliation
    def unreconciled_lines(self, account_id, up_to):
        return self.q("SELECT l.id, e.date, e.ref, e.memo, l.debit, l.credit FROM journal_lines l "
                      "JOIN journal_entries e ON e.id=l.entry_id WHERE l.account_id=? AND l.rec_id IS NULL "
                      "AND e.date<=? ORDER BY e.date, l.id", (account_id, up_to))

    def reconciled_balance(self, account_id):
        return r2(self.val("SELECT SUM(debit-credit) FROM journal_lines WHERE account_id=? AND rec_id IS NOT NULL",
                           (account_id,), 0))

    def reconcile(self, account_id, statement_date, statement_balance, line_ids):
        self.guard_write("journal")
        self.need_module("bank_rec")
        cleared = r2(self.reconciled_balance(account_id) + sum(
            r2(r["debit"]) - r2(r["credit"]) for r in self.q(
                f"SELECT debit, credit FROM journal_lines WHERE id IN ({','.join('?' * len(line_ids)) or 'NULL'})",
                list(line_ids))))
        if abs(cleared - r2(statement_balance)) > EPS:
            raise AccError(f"Cleared balance {cleared:,.2f} does not match the statement balance "
                           f"{float(statement_balance):,.2f}. Difference {cleared - float(statement_balance):,.2f}.")
        rid = self.conn.execute("INSERT INTO reconciliations(account_id,statement_date,statement_balance,created_by) "
                                "VALUES(?,?,?,?)", (account_id, statement_date, r2(statement_balance),
                                                    self.username)).lastrowid
        for lid in line_ids:
            self.conn.execute("UPDATE journal_lines SET rec_id=? WHERE id=? AND account_id=?", (rid, lid, account_id))
        self.audit("reconcile", "account", account_id, f"{statement_date} {statement_balance}")
        self.conn.commit()
        return rid

    # ------------------------------------------------------------ period close
    def fy_bounds(self, d: str | None = None):
        d = date.fromisoformat(d or today())
        m = int(self.setting("fy_start_month", 1) or 1)
        start = date(d.year if d.month >= m else d.year - 1, m, 1)
        end = date(start.year + 1, m, 1) - timedelta(days=1)
        return start.isoformat(), end.isoformat()

    def close_year(self, year_end: str):
        """Transfer income and expense balances to Retained Earnings and lock the period."""
        self.guard_write("setup")
        start, end = self.fy_bounds(year_end)
        if year_end != end:
            raise AccError(f"The financial year containing that date ends on {end}.")
        if self.one("SELECT 1 FROM journal_entries WHERE source_type='closing' AND date=?", (end,)):
            raise AccError("This year has already been closed.")
        re_id = self.account_by_subtype("retained")["id"]
        lines, net = [], 0.0
        for a in self.accounts(types=["income", "expense"], active_only=False):
            bal = self.balance(a["id"], as_of=end, start=start)
            if abs(bal) < EPS:
                continue
            if a["type"] == "income":
                lines.append({"account_id": a["id"], "debit": bal} if bal > 0 else {"account_id": a["id"], "credit": -bal})
                net += bal
            else:
                lines.append({"account_id": a["id"], "credit": bal} if bal > 0 else {"account_id": a["id"], "debit": -bal})
                net -= bal
        net = r2(net)
        if net > 0:
            lines.append({"account_id": re_id, "credit": net})
        elif net < 0:
            lines.append({"account_id": re_id, "debit": -net})
        if lines:
            self.post_entry(end, f"Year-end close {start} to {end}", lines, "closing", commit=False)
        self.conn.execute("INSERT INTO settings(key,value) VALUES('lock_date',?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (end,))
        self.audit("close_year", "period", None, f"{start} to {end}, net {net:,.2f}")
        self.conn.commit()
        return net

    def set_lock_date(self, d):
        self.guard_write("setup")
        if d:
            date.fromisoformat(d)
        self.set_setting("lock_date", d or "")
        self.audit("lock", "period", None, d or "unlocked")
        self.conn.commit()

    # ------------------------------------------------------------ opening balances
    def opening_balance(self, d, account_id, amount):
        """Positive amount = normal balance of the account. Offsets Opening Balance Equity."""
        self.guard_write("journal")
        a = self.one("SELECT * FROM accounts WHERE id=?", (account_id,))
        ob = self.account_by_subtype("opening")["id"]
        amount = r2(amount)
        normal_debit = a["type"] in ("asset", "expense")
        if amount < 0:
            normal_debit, amount = not normal_debit, -amount
        lines = ([{"account_id": account_id, "debit": amount}, {"account_id": ob, "credit": amount}] if normal_debit
                 else [{"account_id": ob, "debit": amount}, {"account_id": account_id, "credit": amount}])
        eid = self.post_entry(d, f"Opening balance: {a['code']} {a['name']}", lines, "opening", commit=False)
        self.audit("opening", "account", account_id, f"{amount:,.2f}")
        self.conn.commit()
        return eid

    # ------------------------------------------------------------ reports
    def _sum_by_account(self, start=None, end=None, department_id=None, exclude_closing=False):
        cond, args = ["1=1"], []
        if start:
            cond.append("e.date>=?"); args.append(start)
        if end:
            cond.append("e.date<=?"); args.append(end)
        if department_id:
            cond.append("l.department_id=?"); args.append(department_id)
        if exclude_closing:
            cond.append("e.source_type<>'closing'")
        sql = ("SELECT a.id, a.code, a.name, a.type, a.subtype, COALESCE(SUM(x.debit),0) AS dr, "
               "COALESCE(SUM(x.credit),0) AS cr FROM accounts a LEFT JOIN "
               "(SELECT l.account_id, l.debit, l.credit FROM journal_lines l JOIN journal_entries e "
               "ON e.id=l.entry_id WHERE " + " AND ".join(cond) + ") x ON x.account_id=a.id "
               "GROUP BY a.id ORDER BY a.code")
        return self.q(sql, args)

    def trial_balance(self, as_of=None):
        rows, tdr, tcr = [], 0.0, 0.0
        for a in self._sum_by_account(end=as_of):
            net = r2(a["dr"] - a["cr"])
            if abs(net) < EPS:
                continue
            dr, cr = (net, 0.0) if net > 0 else (0.0, -net)
            tdr += dr; tcr += cr
            rows.append({"code": a["code"], "name": a["name"], "type": a["type"], "debit": dr, "credit": cr})
        return {"rows": rows, "total_debit": r2(tdr), "total_credit": r2(tcr)}

    def profit_loss(self, start, end, department_id=None):
        income, cogs, expenses = [], [], []
        for a in self._sum_by_account(start, end, department_id, exclude_closing=True):
            if a["type"] == "income":
                v = r2(a["cr"] - a["dr"])
                if abs(v) > EPS:
                    income.append({"code": a["code"], "name": a["name"], "amount": v})
            elif a["type"] == "expense":
                v = r2(a["dr"] - a["cr"])
                if abs(v) > EPS:
                    row = {"code": a["code"], "name": a["name"], "amount": v}
                    (cogs if a["code"].startswith("5") else expenses).append(row)
        ti, tc, te = (r2(sum(r["amount"] for r in x)) for x in (income, cogs, expenses))
        return {"income": income, "cogs": cogs, "expenses": expenses, "total_income": ti, "total_cogs": tc,
                "gross_profit": r2(ti - tc), "total_expenses": te, "net_profit": r2(ti - tc - te)}

    def department_pl(self, start, end):
        rows = []
        for d in self.departments(active_only=False):
            pl = self.profit_loss(start, end, d["id"])
            rows.append({"department": d["name"], "income": pl["total_income"],
                         "costs": r2(pl["total_cogs"] + pl["total_expenses"]), "profit": pl["net_profit"]})
        return rows

    def balance_sheet(self, as_of):
        assets, liabs, equity = [], [], []
        fy_start, _ = self.fy_bounds(as_of)
        for a in self._sum_by_account(end=as_of):
            if a["type"] == "asset":
                v = r2(a["dr"] - a["cr"])
                if abs(v) > EPS:
                    assets.append({"code": a["code"], "name": a["name"], "amount": v})
            elif a["type"] in ("liability", "equity"):
                v = r2(a["cr"] - a["dr"])
                if abs(v) > EPS:
                    (liabs if a["type"] == "liability" else equity).append(
                        {"code": a["code"], "name": a["name"], "amount": v})
        # all unclosed profit to date (income - expense up to as_of, net of closing entries)
        unclosed = 0.0
        for a in self._sum_by_account(end=as_of):
            if a["type"] == "income":
                unclosed += a["cr"] - a["dr"]
            elif a["type"] == "expense":
                unclosed -= a["dr"] - a["cr"]
        unclosed = r2(unclosed)
        if abs(unclosed) > EPS:
            equity.append({"code": "", "name": "Current Year Earnings", "amount": unclosed})
        ta, tl, te = (r2(sum(r["amount"] for r in x)) for x in (assets, liabs, equity))
        return {"assets": assets, "liabilities": liabs, "equity": equity, "total_assets": ta,
                "total_liabilities": tl, "total_equity": te, "balanced": abs(ta - tl - te) < 0.01}

    def general_ledger(self, account_id, start, end):
        a = self.one("SELECT * FROM accounts WHERE id=?", (account_id,))
        debit_nature = a["type"] in ("asset", "expense")
        opening = self.balance(account_id, as_of=(date.fromisoformat(start) - timedelta(days=1)).isoformat())
        rows, bal = [], opening
        for r in self.q("SELECT e.date, e.ref, e.memo, e.source_type, l.debit, l.credit, l.description, "
                        "d.name AS department FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id "
                        "LEFT JOIN departments d ON d.id=l.department_id WHERE l.account_id=? AND e.date BETWEEN ? AND ? "
                        "ORDER BY e.date, e.id, l.id", (account_id, start, end)):
            bal = r2(bal + (r["debit"] - r["credit"] if debit_nature else r["credit"] - r["debit"]))
            rows.append(dict(r, balance=bal))
        return {"account": a, "opening": opening, "rows": rows, "closing": bal}

    def aging(self, kind="sale", as_of=None):
        as_of = as_of or today()
        buckets = ["Current", "1-30", "31-60", "61-90", "90+"]
        out = {}
        for inv in self.q("SELECT i.*, c.name AS contact FROM invoices i JOIN contacts c ON c.id=i.contact_id "
                          "WHERE i.kind=? AND i.status IN ('open','partial') AND i.date<=?", (kind, as_of)):
            bal = r2(inv["total"] - inv["amount_paid"])
            days = (date.fromisoformat(as_of) - date.fromisoformat(inv["due_date"] or inv["date"])).days
            b = 0 if days <= 0 else 1 if days <= 30 else 2 if days <= 60 else 3 if days <= 90 else 4
            row = out.setdefault(inv["contact"], [0.0] * 5)
            row[b] = r2(row[b] + bal)
        rows = [{"contact": k, **{buckets[i]: v[i] for i in range(5)}, "Total": r2(sum(v))} for k, v in sorted(out.items())]
        totals = {b: r2(sum(r[b] for r in rows)) for b in buckets + ["Total"]}
        return {"buckets": buckets, "rows": rows, "totals": totals}

    def vat_summary(self, start, end):
        out_id = self.account_by_subtype("vat_output")["id"]
        in_id = self.account_by_subtype("vat_input")["id"]
        output = r2(self.val("SELECT SUM(l.credit-l.debit) FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id "
                             "WHERE l.account_id=? AND e.date BETWEEN ? AND ?", (out_id, start, end), 0))
        inp = r2(self.val("SELECT SUM(l.debit-l.credit) FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id "
                          "WHERE l.account_id=? AND e.date BETWEEN ? AND ?", (in_id, start, end), 0))
        sales = r2(self.val("SELECT SUM(subtotal) FROM invoices WHERE kind='sale' AND status<>'void' "
                            "AND date BETWEEN ? AND ?", (start, end), 0))
        purchases = r2(self.val("SELECT SUM(subtotal) FROM invoices WHERE kind='bill' AND status<>'void' "
                                "AND date BETWEEN ? AND ?", (start, end), 0))
        return {"sales_net": sales, "purchases_net": purchases, "output_vat": output, "input_vat": inp,
                "net_vat": r2(output - inp)}

    def customer_statement(self, contact_id, start, end):
        c = self.one("SELECT * FROM contacts WHERE id=?", (contact_id,))
        inv_kind, pay_kind = ("sale", "receipt") if c["kind"] == "customer" else ("bill", "payment")
        def movements(cond, args):
            inv = self.q(f"SELECT date, number AS ref, 'Invoice' AS type, total AS amount FROM invoices "
                         f"WHERE contact_id=? AND kind=? AND status<>'void' AND {cond}", [contact_id, inv_kind] + args)
            pay = self.q(f"SELECT date, number AS ref, 'Payment' AS type, -amount AS amount FROM payments "
                         f"WHERE contact_id=? AND kind=? AND status<>'void' AND {cond}", [contact_id, pay_kind] + args)
            return sorted([dict(r) for r in inv] + [dict(r) for r in pay], key=lambda r: (r["date"], r["ref"]))
        opening = r2(sum(r["amount"] for r in movements("date<?", [start])))
        rows, bal = [], opening
        for r in movements("date BETWEEN ? AND ?", [start, end]):
            bal = r2(bal + r["amount"])
            rows.append(dict(r, balance=bal))
        return {"contact": c, "opening": opening, "rows": rows, "closing": bal}

    def inventory_valuation(self):
        rows = [{"code": i["code"] or "", "name": i["name"], "unit": i["unit"], "qty": i["qty_on_hand"],
                 "cost": i["cost_price"], "value": r2(i["qty_on_hand"] * i["cost_price"]),
                 "low": i["qty_on_hand"] <= i["reorder_level"]}
                for i in self.q("SELECT * FROM items WHERE kind='stock' AND active=1 ORDER BY name")]
        return {"rows": rows, "total": r2(sum(r["value"] for r in rows))}

    def dashboard(self, as_of=None):
        as_of = as_of or today()
        d = date.fromisoformat(as_of)
        m_start = d.replace(day=1).isoformat()
        pl = self.profit_loss(m_start, as_of)
        cash = r2(sum(self.balance(a["id"], as_of) for a in self.bank_accounts()))
        ar = r2(self.val("SELECT SUM(total-amount_paid) FROM invoices WHERE kind='sale' AND status IN ('open','partial')",
                         default=0))
        ap = r2(self.val("SELECT SUM(total-amount_paid) FROM invoices WHERE kind='bill' AND status IN ('open','partial')",
                         default=0))
        overdue = self.val("SELECT COUNT(*) FROM invoices WHERE kind='sale' AND status IN ('open','partial') AND due_date<?",
                           (as_of,), 0)
        months = []
        y, m = d.year, d.month
        for _ in range(6):
            s = date(y, m, 1)
            e = (date(y + (m // 12), m % 12 + 1, 1) - timedelta(days=1))
            p = self.profit_loss(s.isoformat(), e.isoformat())
            months.append({"label": s.strftime("%b"), "income": p["total_income"],
                           "expense": r2(p["total_cogs"] + p["total_expenses"])})
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        months.reverse()
        banks = [{"name": a["name"], "balance": self.balance(a["id"], as_of)} for a in self.bank_accounts()]
        recent = self.q("SELECT date, ref, memo, (SELECT SUM(debit) FROM journal_lines WHERE entry_id=e.id) AS amount "
                        "FROM journal_entries e ORDER BY id DESC LIMIT 8")
        paid_out = r2(self.val(
            "SELECT SUM(l.credit - l.debit) FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id "
            "JOIN accounts a ON a.id=l.account_id WHERE a.subtype IN ('bank','cash') AND e.date BETWEEN ? AND ? "
            "AND e.source_type IN ('expense','payment')", (m_start, as_of), 0))
        stock_bought = r2(self.val(
            "SELECT SUM(l.net) FROM invoice_lines l JOIN invoices i ON i.id=l.invoice_id JOIN items it "
            "ON it.id=l.item_id WHERE i.kind='bill' AND i.status<>'void' AND it.kind='stock' AND i.date BETWEEN ? AND ?",
            (m_start, as_of), 0))
        return {"paid_out_month": paid_out, "stock_bought_month": stock_bought, "income_month": pl["total_income"], "expense_month": r2(pl["total_cogs"] + pl["total_expenses"]),
                "profit_month": pl["net_profit"], "cash": cash, "receivables": ar, "payables": ap,
                "overdue": overdue, "months": months, "banks": banks, "recent": recent}

    def audit_trail(self, limit=1000, search=""):
        sql, args = "SELECT * FROM audit_log", []
        if search:
            sql += " WHERE username LIKE ? OR action LIKE ? OR entity LIKE ? OR details LIKE ?"
            args = [f"%{search}%"] * 4
        return self.q(sql + " ORDER BY id DESC LIMIT ?", args + [limit])

    # ------------------------------------------------------------ backup
    def backup(self, dest_dir) -> Path:
        self.require("backup")
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        name = f"{self.path.stem}_{datetime.now():%Y%m%d_%H%M%S}.nacc.bak"
        target = dest_dir / name
        bconn = sqlite3.connect(str(target))
        with bconn:
            self.conn.backup(bconn)
        bconn.close()
        self.audit("backup", "company", None, str(target))
        self.conn.commit()
        return target

    @staticmethod
    def restore(backup_file, company_path):
        """Replace a company file with a backup (call with the company closed)."""
        test = sqlite3.connect(str(backup_file))
        try:
            ok = test.execute("SELECT value FROM settings WHERE key='company_name'").fetchone()
        except sqlite3.DatabaseError:
            ok = None
        finally:
            test.close()
        if not ok:
            raise AccError("That file is not a Nolima Accounting backup.")
        company_path = Path(company_path)
        if company_path.exists():
            shutil.copy2(company_path, company_path.with_suffix(".before_restore"))
        for ext in ("-wal", "-shm"):
            p = Path(str(company_path) + ext)
            if p.exists():
                p.unlink()
        shutil.copy2(backup_file, company_path)

    def close(self):
        try:
            self.conn.commit()
            self.conn.close()
        except Exception:
            pass


def export_csv(path, headers, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for r in rows:
            w.writerow(r)
    return path
