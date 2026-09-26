"""Industry chart-of-accounts templates.

Each entry: (code, name, type, subtype). Types: asset, liability, equity,
income, expense. Subtypes marked below are used by the posting engine and
must exist in every template (they come from BASE).
"""

BASE = [
    # Assets
    ("1000", "Cash on Hand", "asset", "cash"),
    ("1010", "Bank - Current Account", "asset", "bank"),
    ("1020", "Mobile Money (Airtel Money / TNM Mpamba)", "asset", "bank"),
    ("1100", "Accounts Receivable (Debtors)", "asset", "receivable"),
    ("1150", "VAT Input (Recoverable)", "asset", "vat_input"),
    ("1160", "Withholding Tax Receivable (certificates)", "asset", "wht_receivable"),
    ("1200", "Inventory", "asset", "inventory"),
    ("1300", "Prepayments", "asset", "other"),
    ("1500", "Furniture and Fittings", "asset", "fixed_asset"),
    ("1510", "Motor Vehicles", "asset", "fixed_asset"),
    ("1520", "Computer Equipment", "asset", "fixed_asset"),
    ("1590", "Accumulated Depreciation", "asset", "contra_asset"),
    # Liabilities
    ("2000", "Accounts Payable (Creditors)", "liability", "payable"),
    ("2100", "VAT Output (Payable to MRA)", "liability", "vat_output"),
    ("2120", "Tourism Levy Payable", "liability", "tourism_levy"),
    ("2130", "Withholding Tax Payable (annual)", "liability", "wht_payable"),
    ("2150", "PAYE Payable", "liability", "other"),
    ("2200", "Accrued Expenses", "liability", "other"),
    ("2300", "Customer Deposits", "liability", "other"),
    ("2500", "Loans Payable", "liability", "other"),
    # Equity
    ("3000", "Owner's Capital", "equity", "other"),
    ("3100", "Retained Earnings", "equity", "retained"),
    ("3200", "Owner's Drawings", "equity", "other"),
    ("3900", "Opening Balance Equity", "equity", "opening"),
    # Cost of sales
    ("5000", "Cost of Goods Sold", "expense", "cogs"),
    # Common expenses
    ("6000", "Salaries and Wages", "expense", "other"),
    ("6010", "Staff Welfare", "expense", "other"),
    ("6100", "Rent", "expense", "other"),
    ("6110", "Electricity (ESCOM)", "expense", "other"),
    ("6120", "Water", "expense", "other"),
    ("6130", "Telephone and Internet", "expense", "other"),
    ("6200", "Repairs and Maintenance", "expense", "other"),
    ("6210", "Fuel and Transport", "expense", "other"),
    ("6300", "Stationery and Printing", "expense", "other"),
    ("6310", "Advertising and Marketing", "expense", "other"),
    ("6400", "Bank Charges", "expense", "other"),
    ("6410", "Mobile Money Charges", "expense", "other"),
    ("6500", "Professional Fees", "expense", "other"),
    ("6510", "Licences and Subscriptions", "expense", "other"),
    ("6600", "Insurance", "expense", "other"),
    ("6700", "Depreciation", "expense", "other"),
    ("6900", "Sundry Expenses", "expense", "other"),
    # Other income
    ("4900", "Other Income", "income", "other"),
    ("4910", "Interest Received", "income", "other"),
]

INDUSTRY = {
    "General business": [
        ("4000", "Sales", "income", "other"),
        ("4010", "Service Income", "income", "other"),
    ],
    "Hospitality (hotel, lodge, restaurant)": [
        ("4000", "Room Revenue", "income", "other"),
        ("4010", "Food Revenue", "income", "other"),
        ("4020", "Beverage and Bar Revenue", "income", "other"),
        ("4030", "Conference and Events Revenue", "income", "other"),
        ("4040", "Laundry and Other Guest Services", "income", "other"),
        ("5010", "Cost of Food", "expense", "other"),
        ("5020", "Cost of Beverages", "expense", "other"),
        ("5030", "Guest Amenities", "expense", "other"),
        ("6020", "Housekeeping Supplies", "expense", "other"),
        ("6030", "Linen and Laundry", "expense", "other"),
        ("6040", "Tourism Levy", "expense", "other"),
    ],
    "Retail and wholesale": [
        ("4000", "Sales - Goods", "income", "other"),
        ("4010", "Delivery Income", "income", "other"),
        ("4090", "Sales Returns and Discounts", "income", "other"),
        ("5010", "Freight and Clearing", "expense", "other"),
        ("5020", "Stock Losses and Write-offs", "expense", "other"),
    ],
    "Professional services": [
        ("4000", "Consulting Fees", "income", "other"),
        ("4010", "Project Income", "income", "other"),
        ("4020", "Training Income", "income", "other"),
        ("5010", "Subcontractor Costs", "expense", "other"),
    ],
    "NGO / non-profit": [
        ("4000", "Grant Income - Restricted", "income", "other"),
        ("4010", "Grant Income - Unrestricted", "income", "other"),
        ("4020", "Donations", "income", "other"),
        ("5010", "Programme Costs", "expense", "other"),
        ("5020", "Field Allowances", "expense", "other"),
        ("5030", "Workshops and Meetings", "expense", "other"),
    ],
    "Manufacturing": [
        ("4000", "Sales - Finished Goods", "income", "other"),
        ("1210", "Raw Materials", "asset", "other"),
        ("1220", "Work in Progress", "asset", "other"),
        ("5010", "Direct Materials", "expense", "other"),
        ("5020", "Direct Labour", "expense", "other"),
        ("5030", "Factory Overheads", "expense", "other"),
    ],
    "Agriculture": [
        ("4000", "Crop Sales", "income", "other"),
        ("4010", "Livestock Sales", "income", "other"),
        ("5010", "Seed and Fertiliser", "expense", "other"),
        ("5020", "Chemicals", "expense", "other"),
        ("5030", "Casual Labour", "expense", "other"),
    ],
    "School / education": [
        ("4000", "Tuition Fees", "income", "other"),
        ("4010", "Boarding Fees", "income", "other"),
        ("4020", "Examination Fees", "income", "other"),
        ("5010", "Teaching Materials", "expense", "other"),
        ("5020", "Boarding Food Costs", "expense", "other"),
    ],
}

DEPARTMENTS = {
    "Hospitality (hotel, lodge, restaurant)": ["Rooms", "Restaurant", "Bar", "Conference", "Administration"],
    "School / education": ["Primary", "Secondary", "Boarding", "Administration"],
    "NGO / non-profit": ["Programmes", "Administration"],
}


def template(industry: str):
    rows = {code: (code, name, t, st) for code, name, t, st in BASE}
    for row in INDUSTRY.get(industry, INDUSTRY["General business"]):
        rows[row[0]] = row
    return sorted(rows.values(), key=lambda r: r[0])
