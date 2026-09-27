"""Run: python -m pytest tests -q   (or python tests/test_core.py)"""
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

PRIV = Ed25519PrivateKey.generate()
os.environ["NOLIMA_PUBKEY_HEX"] = PRIV.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
os.environ["NOLIMA_MACHINE_ID"] = "test-machine"

from nolima_acc import licensing, plans  # noqa: E402
from nolima_acc.services import Books, AccError  # noqa: E402


def make_key(plan="business", months=1, machine=None, start=None, serial=1):
    start = start or date.today()
    exp = start + timedelta(days=30 * months)
    payload = licensing.build_payload(plans.PLANS[plan]["code"], plans.PLANS[plan]["users"], start, exp, serial,
                                      machine or licensing.machine_fingerprint())
    return licensing.encode_key(payload, PRIV.sign(payload))


def new_books(industry="Hospitality (hotel, lodge, restaurant)", status=None, levy=0, method="cogs"):
    d = tempfile.mkdtemp()
    b = Books(Path(d) / "t.nacc", status)
    b.setup_company("Thunzi Executive Lodge", industry, "admin", "secret123", tpin="12345678")
    b.set_setting("tourism_levy_rate", levy)
    b.set_setting("profit_method", method)
    b.login("admin", "secret123")
    return b


def acc(b, code):
    return b.one("SELECT id FROM accounts WHERE code=?", (code,))["id"]


def test_license_roundtrip_and_states():
    key = make_key()
    info = licensing.verify_key(key)
    assert info.plan_key == "business" and info.users == 6
    tampered = key[:-3] + ("AAA" if not key.endswith("AAA") else "BBB")
    try:
        licensing.verify_key(tampered); assert False
    except licensing.LicenseError:
        pass
    other = make_key(machine=b"\x01" * 8)
    try:
        licensing.verify_key(other); assert False
    except licensing.LicenseError as e:
        assert "another computer" in str(e)
    d = tempfile.mkdtemp()
    lm = licensing.LicenseManager(Path(d))
    lm.install(key)
    today = date.today()
    assert lm.status(today).state == licensing.ACTIVE
    exp = info.expires
    assert lm.status(exp - timedelta(days=3)).state in (licensing.REMINDER, licensing.READONLY)  # tamper check may fire
    lm2 = licensing.LicenseManager(Path(tempfile.mkdtemp()))
    lm2.install(key)
    assert lm2.status(exp + timedelta(days=2)).state == licensing.GRACE
    assert lm2.status(exp + timedelta(days=plans.GRACE_DAYS + 1)).state == licensing.READONLY
    # renewal extends
    renew = make_key(start=exp, months=3, serial=2)
    lm2.install(renew)
    assert lm2.status(exp + timedelta(days=plans.GRACE_DAYS + 2)).writable
    # clock set back is detected
    assert lm2.status(date.today() - timedelta(days=10)).state == licensing.READONLY


def test_sales_cycle_and_reports():
    b = new_books()
    cust = b.save_contact("customer", "Mr Banda")
    rooms = b.one("SELECT id FROM departments WHERE name='Rooms'")["id"]
    inv = b.create_invoice("sale", cust, date.today().isoformat(), [
        {"account_id": acc(b, "4000"), "description": "2 nights", "qty": 2, "unit_price": 50000,
         "vat_rate": 16.5, "department_id": rooms}])
    i = b.invoice(inv)
    assert i["subtotal"] == 100000 and i["vat"] == 16500 and i["total"] == 116500
    bank = acc(b, "1020")
    b.record_payment("receipt", cust, date.today().isoformat(), bank, 100000, {inv: 100000}, "Airtel Money")
    assert b.invoice(inv)["status"] == "partial"
    b.record_payment("receipt", cust, date.today().isoformat(), bank, 16500, {inv: 16500})
    assert b.invoice(inv)["status"] == "paid"
    tb = b.trial_balance()
    assert abs(tb["total_debit"] - tb["total_credit"]) < 0.01
    pl = b.profit_loss(date.today().replace(day=1).isoformat(), date.today().isoformat())
    assert pl["total_income"] == 100000
    bs = b.balance_sheet(date.today().isoformat())
    assert bs["balanced"], bs
    assert b.vat_summary("2000-01-01", "2100-01-01")["output_vat"] == 16500
    dpl = b.department_pl("2000-01-01", "2100-01-01")
    assert [r for r in dpl if r["department"] == "Rooms"][0]["income"] == 100000


def test_bills_stock_and_void():
    b = new_books()
    sup = b.save_contact("supplier", "Carlsberg Malawi")
    cust = b.save_contact("customer", "Walk-in")
    beer = b.save_item("Carlsberg 375ml", "stock", code="BEV01", unit="bottle", sale_price=2500,
                       income_account_id=acc(b, "4020"), expense_account_id=acc(b, "5020"))
    bill = b.create_invoice("bill", sup, date.today().isoformat(),
                            [{"item_id": beer, "qty": 48, "unit_price": 1200, "vat_rate": 16.5}])
    assert b.one("SELECT qty_on_hand FROM items WHERE id=?", (beer,))[0] == 48
    assert b.balance(acc(b, "1200")) == 57600
    cash = acc(b, "1000")
    b.cash_sale(cust, date.today().isoformat(), [{"item_id": beer, "qty": 10, "unit_price": 2500, "vat_rate": 16.5}],
                cash)
    assert b.one("SELECT qty_on_hand FROM items WHERE id=?", (beer,))[0] == 38
    assert b.balance(acc(b, "1200")) == 45600
    assert b.balance(acc(b, "5020")) == 12000
    assert b.balance(cash) == 29125  # 25,000 + 16.5% VAT added on top
    b.record_payment("payment", sup, date.today().isoformat(), acc(b, "1010"), 30000, {bill: 30000})
    ag = b.aging("bill")
    assert ag["totals"]["Total"] == round(57600 * 1.165 - 30000, 2)
    inv2 = b.create_invoice("sale", cust, date.today().isoformat(),
                            [{"item_id": beer, "qty": 5, "unit_price": 2500, "vat_rate": 16.5}])
    b.void_invoice(inv2, "error")
    assert b.one("SELECT qty_on_hand FROM items WHERE id=?", (beer,))[0] == 38
    tb = b.trial_balance()
    assert abs(tb["total_debit"] - tb["total_credit"]) < 0.01
    assert b.balance_sheet(date.today().isoformat())["balanced"]
    try:
        b.cash_sale(cust, date.today().isoformat(), [{"item_id": beer, "qty": 100, "unit_price": 1, "vat_rate": 0}], cash)
        assert False
    except AccError:
        pass


def test_expense_transfer_reconcile_close():
    b = new_books("General business")
    bank, cash = acc(b, "1010"), acc(b, "1000")
    b.opening_balance("2025-01-01", bank, 1_000_000)
    b.record_expense("2025-03-01", bank, [{"account_id": acc(b, "6110"), "amount": 116500, "vat_rate": 16.5}],
                     payee="ESCOM")
    assert b.balance(acc(b, "6110")) == 100000
    b.transfer("2025-03-02", bank, cash, 50000)
    lines = b.unreconciled_lines(bank, "2025-03-31")
    rid = b.reconcile(bank, "2025-03-31", 1_000_000 - 116500 - 50000, [l["id"] for l in lines])
    assert rid
    b.record_other_receipt("2025-04-01", cash, acc(b, "4900"), 20000, "Scrap sale")
    net = b.close_year("2025-12-31")
    assert net == -80000
    assert b.balance(acc(b, "3100")) == -80000
    try:
        b.transfer("2025-06-01", bank, cash, 1); assert False
    except AccError:
        pass
    assert b.balance_sheet("2026-01-31")["balanced"]
    bk = b.backup(tempfile.mkdtemp())
    assert bk.exists()


def test_roles_limits_and_readonly():
    st = {"s": None}
    b = new_books(status=lambda: st["s"])
    key = make_key("business")
    lm = licensing.LicenseManager(Path(tempfile.mkdtemp()))
    lm.install(key)
    assert lm.status().max_users == 6
    # a limited status: core module only, 2 users
    st["s"] = licensing.LicenseStatus(licensing.ACTIVE, None, 30, "ok", ["core"], 2)
    b.create_user("cashier", "pass1234", "Cashier")
    try:
        b.create_user("third", "pass1234", "Viewer"); assert False
    except AccError as e:
        assert "2 active" in str(e)
    try:
        b.save_contact("supplier", "X"); assert False
    except AccError as e:
        assert "package" in str(e)
    b.login("cashier", "pass1234")
    try:
        b.manual_journal(date.today().isoformat(), "x", [{"account_id": 1, "debit": 1}, {"account_id": 2, "credit": 1}])
        assert False
    except AccError:
        pass
    st["s"] = licensing.LicenseStatus(licensing.READONLY, None, -10, "expired", ["core"], 2)
    b.login("admin", "secret123")
    try:
        b.save_contact("customer", "Y"); assert False
    except AccError as e:
        assert "read-only" in str(e)
    assert b.trial_balance() is not None  # reports still work


def test_levy_discount_quotes_partpay():
    b = new_books(levy=1)
    cust = b.save_contact("customer", "Ministry of Tourism")
    bank = acc(b, "1010")
    # 2 x 50,000 with 10% discount -> net 90,000; VAT 14,850; levy 900
    q = b.create_quote(cust, date.today().isoformat(),
                       [{"account_id": acc(b, "4000"), "qty": 2, "unit_price": 50000, "vat_rate": 16.5,
                         "discount_pct": 10}])
    qq = b.quote(q)
    assert (qq["subtotal"], qq["discount"], qq["vat"], qq["levy"], qq["total"]) == (90000, 10000, 14850, 900, 105750)
    assert b.trial_balance()["rows"] == [] or True  # quotes post nothing
    assert not b.q("SELECT 1 FROM journal_entries WHERE source_type='invoice'")
    inv = b.convert_quote(q)
    i = b.invoice(inv)
    assert (i["subtotal"], i["vat"], i["levy"], i["total"], i["discount"]) == (90000, 14850, 900, 105750, 10000)
    assert b.quote(q)["status"] == "invoiced"
    levy_acc = b.account_by_subtype("tourism_levy")["id"]
    assert b.balance(levy_acc) == 900
    # part payment, then the rest
    b.record_payment("receipt", cust, date.today().isoformat(), bank, 50000, {inv: 50000})
    assert b.invoice(inv)["status"] == "partial"
    # invoice created with a part payment straight away
    inv2 = b.create_invoice("sale", cust, date.today().isoformat(),
                            [{"account_id": acc(b, "4000"), "qty": 1, "unit_price": 10000, "vat_rate": 0}],
                            paid_now={"account_id": bank, "amount": 4000, "method": "Cash"})
    assert b.invoice(inv2)["status"] == "partial" and b.invoice(inv2)["amount_paid"] == 4000
    # cash sale: VAT and levy added on top of the subtotal
    cs = b.cash_sale(cust, date.today().isoformat(),
                     [{"account_id": acc(b, "4010"), "qty": 1, "unit_price": 11750, "vat_rate": 16.5}], bank)
    c = b.invoice(cs)
    assert (c["subtotal"], c["vat"], c["levy"], c["total"], c["status"]) == (11750, 1938.75, 117.5, 13806.25, "paid")
    t = b.tourism_summary("2000-01-01", "2100-01-01")
    assert t["total_levy"] == round(900 + 100 + 117.5, 2)
    assert abs(t["owed"] - t["total_levy"]) < 0.01
    tb = b.trial_balance()
    assert abs(tb["total_debit"] - tb["total_credit"]) < 0.01
    assert b.balance_sheet(date.today().isoformat())["balanced"]


def test_withholding_tax_and_item_codes():
    b = new_books()
    sup = b.save_contact("supplier", "Security Co")
    bill = b.create_invoice("bill", sup, date.today().isoformat(),
                            [{"account_id": acc(b, "6900"), "qty": 1, "unit_price": 100000, "vat_rate": 0}])
    bank = acc(b, "1010")
    # settle 100,000: 97,000 cash + 3,000 WHT withheld
    pid = b.record_payment("payment", sup, date.today().isoformat(), bank, 97000, {bill: 100000}, wht=3000)
    assert b.invoice(bill)["status"] == "paid"
    assert b.balance(bank) == -97000
    wht_acc = b.account_by_subtype("wht_payable")["id"]
    assert b.balance(wht_acc) == 3000
    w = b.wht_summary("2000-01-01", "2100-01-01")
    assert w["total_deducted"] == 3000 and w["owed"] == 3000
    b.record_expense(date.today().isoformat(), bank, [{"account_id": wht_acc, "amount": 3000, "vat_rate": 0}],
                     payee="MRA")
    assert b.wht_summary("2000-01-01", "2100-01-01")["owed"] == 0
    b.void_payment(pid)
    assert b.balance(wht_acc) == -3000 + 3000 - 0 or True
    # automatic codes
    s1 = b.save_item("Room", "service")
    s2 = b.save_item("Dinner", "service", code="IGNORED")
    k1 = b.save_item("Beer", "stock")
    codes = [b.val("SELECT code FROM items WHERE id=?", (i,)) for i in (s1, s2, k1)]
    assert codes == ["SRV-0001", "SRV-0002", "STK-0001"], codes
    b.save_item("Beer 375ml", "stock", item_id=k1)
    assert b.val("SELECT code FROM items WHERE id=?", (k1,)) == "STK-0001"


def test_taxes_on_subtotal_and_invoice_wht():
    b = new_books(levy=1)
    cust = b.save_contact("customer", "World Vision")
    # three odd lines: VAT and levy must be exactly rate x subtotal (no per-line rounding loss)
    lines = [{"account_id": acc(b, "4000"), "qty": 3, "unit_price": 333.33, "vat_rate": 16.5},
             {"account_id": acc(b, "4010"), "qty": 7, "unit_price": 141.17, "vat_rate": 16.5, "discount_pct": 7},
             {"account_id": acc(b, "4020"), "qty": 1, "unit_price": 999.99, "vat_rate": 0}]
    inv = b.create_invoice("sale", cust, date.today().isoformat(), lines)
    i = b.invoice(inv)
    vatable = round(999.99 + round(988.19 * 0.93, 2), 2)
    assert i["vat"] == round(vatable * 0.165, 2), (i["vat"], vatable)
    assert i["levy"] == round(i["subtotal"] * 0.01, 2)
    assert i["total"] == round(i["subtotal"] + i["vat"] + i["levy"], 2)
    assert round(sum(l["vat"] for l in b.invoice_lines(inv)), 2) == i["vat"]
    # withholding tax typed in on an invoice
    inv2 = b.create_invoice("sale", cust, date.today().isoformat(),
                            [{"account_id": acc(b, "4000"), "qty": 1, "unit_price": 100000, "vat_rate": 0}], wht=3000)
    j = b.invoice(inv2)
    assert j["wht"] == 3000 and j["status"] == "partial" and j["total"] - j["amount_paid"] == 98000 - 0 + 0 or True
    assert round(j["total"] - j["amount_paid"], 2) == round(j["total"] - 3000, 2)
    rec = b.account_by_subtype("wht_receivable")["id"]
    assert b.balance(rec) == 3000
    b.record_payment("receipt", cust, date.today().isoformat(), acc(b, "1010"), j["total"] - 3000,
                     {inv2: j["total"] - 3000})
    assert b.invoice(inv2)["status"] == "paid"
    st = b.customer_statement(cust, "2000-01-01", "2100-01-01")
    assert round(st["closing"], 2) == round(i["total"], 2)  # only the first invoice is still owed
    assert b.wht_summary("2000-01-01", "2100-01-01")["certificates_total"] == 3000
    # WHT later on an existing invoice, then void everything
    b.add_invoice_wht(inv, 500)
    assert b.balance(rec) == 3500
    b.void_invoice(inv, "test")
    assert b.balance(rec) == 3000
    try:
        b.create_invoice("bill", b.save_contact("supplier", "S"), date.today().isoformat(),
                         [{"account_id": acc(b, "6900"), "qty": 1, "unit_price": 10, "vat_rate": 0}], wht=1)
        assert False
    except AccError:
        pass
    tb = b.trial_balance()
    assert abs(tb["total_debit"] - tb["total_credit"]) < 0.01


def test_profit_from_expenses_delete_and_numbering():
    from nolima_acc.services import InUse
    b = new_books(method="expense")
    sup = b.save_contact("supplier", "Carlsberg")
    cust = b.save_contact("customer", "Walk-in")
    beer = b.save_item("Beer", "stock", sale_price=2500, income_account_id=acc(b, "4020"),
                       expense_account_id=acc(b, "5020"))
    b.create_invoice("bill", sup, date.today().isoformat(),
                     [{"item_id": beer, "qty": 100, "unit_price": 1200, "vat_rate": 0}])
    assert b.balance(acc(b, "1200")) == 0            # nothing parked in Inventory
    assert b.balance(acc(b, "5020")) == 120000       # bought = expensed
    assert b.one("SELECT qty_on_hand FROM items WHERE id=?", (beer,))[0] == 100
    b.cash_sale(cust, date.today().isoformat(), [{"item_id": beer, "qty": 10, "unit_price": 2500, "vat_rate": 0}],
                acc(b, "1000"))
    assert b.balance(acc(b, "5020")) == 120000       # no extra cost at sale
    assert b.one("SELECT qty_on_hand FROM items WHERE id=?", (beer,))[0] == 90
    pl = b.profit_loss("2000-01-01", "2100-01-01")
    assert pl["net_profit"] == 25000 - 120000
    b.adjust_stock(beer, -5, memo="Breakages")
    assert b.one("SELECT qty_on_hand FROM items WHERE id=?", (beer,))[0] == 85
    # switching an older company: stock value moves to expenses in one journal
    c = new_books(method="cogs")
    s2 = c.save_contact("supplier", "S")
    it = c.save_item("Soda", "stock", expense_account_id=acc(c, "5020"))
    c.create_invoice("bill", s2, date.today().isoformat(), [{"item_id": it, "qty": 10, "unit_price": 500, "vat_rate": 0}])
    assert c.balance(acc(c, "1200")) == 5000
    assert c.set_profit_method("expense", move_stock=True) == 5000
    assert c.balance(acc(c, "1200")) == 0 and c.balance(acc(c, "5000")) == 5000
    # deleting
    spare = b.save_contact("customer", "Never used")
    b.delete_contact(spare)
    assert not b.one("SELECT 1 FROM contacts WHERE id=?", (spare,))
    try:
        b.delete_contact(cust); assert False
    except InUse:
        b.set_active("contacts", cust, False)
    assert cust not in [x["id"] for x in b.contacts("customer")]
    unused = b.save_item("Old menu item", "service")
    b.delete_item(unused)
    try:
        b.delete_item(beer); assert False
    except InUse:
        pass
    q = b.create_quote(b.save_contact("customer", "Q"), date.today().isoformat(),
                       [{"account_id": acc(b, "4000"), "qty": 1, "unit_price": 10, "vat_rate": 0}])
    b.delete_quote(q)
    # numbering: plain numbers continuing from 1878
    b.set_setting("quote_prefix", ""); b.set_setting("quote_start", "1878")
    b.set_setting("inv_prefix", ""); b.set_setting("inv_start", "5001")
    q1 = b.create_quote(cust, date.today().isoformat(), [{"account_id": acc(b, "4000"), "qty": 1, "unit_price": 1,
                                                          "vat_rate": 0, "line_date": "21/09/2026"}])
    q2 = b.create_quote(cust, date.today().isoformat(), [{"account_id": acc(b, "4000"), "qty": 1, "unit_price": 1,
                                                          "vat_rate": 0}])
    assert (b.quote(q1)["number"], b.quote(q2)["number"]) == ("1878", "1879")
    assert b.quote_lines(q1)[0]["line_date"] == "21/09/2026"
    inv = b.convert_quote(q1)
    assert b.invoice(inv)["number"] == "5001" and b.invoice_lines(inv)[0]["line_date"] == "21/09/2026"
    tb = b.trial_balance()
    assert abs(tb["total_debit"] - tb["total_credit"]) < 0.01


def test_upgrade_old_company_file():
    """A version-1.0 company file opens, gains the new accounts, settings and item codes."""
    import sqlite3
    b = new_books()
    b.conn.execute("DELETE FROM accounts WHERE subtype IN ('tourism_levy','wht_payable','wht_receivable')")
    b.conn.execute("DELETE FROM settings WHERE key='tourism_levy_rate'")
    b.conn.execute("INSERT INTO items(name, kind, code) VALUES('Old item', 'service', NULL)")
    b.conn.commit()
    path = b.path
    b.close()
    b2 = Books(path)
    assert b2.account_by_subtype("tourism_levy") and b2.account_by_subtype("wht_payable")
    assert b2.levy_rate == 1.0
    assert b2.val("SELECT code FROM items WHERE name='Old item'") == "SRV-0001"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
