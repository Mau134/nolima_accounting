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


def new_books(industry="Hospitality (hotel, lodge, restaurant)", status=None):
    d = tempfile.mkdtemp()
    b = Books(Path(d) / "t.nacc", status)
    b.setup_company("Thunzi Executive Lodge", industry, "admin", "secret123", tpin="12345678")
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
    assert b.balance(cash) == 25000
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
