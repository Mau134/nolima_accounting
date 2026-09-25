"""Licence packages. Shared by the application and the licence generator.

Change prices here; both programs pick them up. Plan codes are embedded in
licence keys, so never renumber an existing plan.
"""

MODULES = {
    "core": "Core accounting (accounts, journals, sales, receipts, expenses, banking, VAT, reports)",
    "purchases": "Supplier bills, supplier payments and creditors aging",
    "bank_rec": "Bank reconciliation",
    "inventory": "Inventory / stock items",
    "departments": "Departments and departmental P&L",
    "multi_company": "Multiple companies",
    "audit_viewer": "Audit trail viewer",
}

PLANS = {
    # code 1 (the former Starter package) is retired; never reuse it
    "business": {
        "code": 2, "name": "Business", "monthly": 85_000, "users": 6,
        "modules": ["core", "purchases", "bank_rec", "inventory", "departments"],
        "support": "Phone and WhatsApp support, business hours",
    },
    "enterprise": {
        "code": 3, "name": "Enterprise", "monthly": 150_000, "users": 0,  # 0 = unlimited
        "modules": list(MODULES.keys()),
        "support": "Same-day priority support",
    },
}

# Billing cycles: months covered and how many months are charged
CYCLES = {
    "monthly": {"name": "Monthly", "months": 1, "charge_months": 1.0},
    "quarterly": {"name": "Quarterly (5% off)", "months": 3, "charge_months": 3 * 0.95},
    "annual": {"name": "Annual (2 months free)", "months": 12, "charge_months": 10.0},
}

GRACE_DAYS = 7          # after expiry, full access continues this many days
REMINDER_DAYS = 14      # start reminding this many days before expiry
TRIAL_DAYS = 14         # unlicensed installs run as a trial for this long


def plan_by_code(code: int):
    for key, p in PLANS.items():
        if p["code"] == code:
            return key, p
    return None, None


def cycle_price(plan_key: str, cycle_key: str) -> float:
    return round(PLANS[plan_key]["monthly"] * CYCLES[cycle_key]["charge_months"], 2)
