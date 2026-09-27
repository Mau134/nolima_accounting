# Nolima Accounting 1.3

## Default login

| | |
| --- | --- |
| Username | `admin` |
| Password | `admin123` |

These are pre-filled when a company is first set up. After the first sign-in the program asks the
administrator to choose a new password. Other staff get their own logins under **Settings > Users**.

Professional double-entry accounting for any industry, by Nolima Tech Consultants.
Python 3.10+ · Tkinter · SQLite · Ed25519-signed monthly licences.

## Features

Double-entry accounting for any industry: invoices, **quotations**, cash sales, supplier bills, receipts and
payments (with **part payments**), expenses, transfers, bank reconciliation, stock with average costing,
departments, VAT, **1% tourism levy**, **withholding tax**, **line discounts**, year-end close, users and roles,
audit trail, backups, 13 reports (including **Tourism levy summary** and **Withholding tax summary**),
printable documents with the company's **bank and mobile money details**, signed licences and remote updates.

### Tax settings (Settings > Company)

| Setting | Default | Effect |
| --- | --- | --- |
| VAT rate | 17.5% | Calculated on the subtotal (after discounts) and added on top |
| Tourism levy | 1% | Calculated on the subtotal and added to every sale; posted to 2120 Tourism Levy Payable. Set 0 for businesses that do not charge it; can be switched off per invoice |
| Withholding tax | typed in per invoice | Customer invoices only: the amount the customer deducts is entered by hand (on the invoice or later with Sales > Withholding tax). It reduces what the customer owes and is posted to 1160 Withholding Tax Receivable |

| Profit method | From expenses | Stock bought is an expense when bought (profit = income - expenses); quantities are still tracked. Alternative: cost of sales when sold |

Prices are always entered before VAT and levy. Documents print up to three banks plus mobile money
(Settings > Bank details). Invoices and quotations follow the lodge's own layout: logo, date / total / due-date
boxes, line dates, one TAX line and a TAX SUMMARY (Ministry of Tourism and MRA). Numbering can continue from
existing numbers (Settings > Company: blank prefix and "next number", e.g. 1878). Unused customers,
suppliers, items and quotations can be deleted; used ones can be hidden.

Company files from earlier versions are upgraded automatically when opened: the new accounts, settings and item codes
are added and nothing existing is changed.

## What's in the box

| Path | What it is |
| --- | --- |
| `main.py` | Starts Nolima Accounting |
| `nolima_acc/services.py` | Accounting engine: double-entry posting, invoices, bills, receipts, payments, expenses, transfers, stock, reconciliation, year-end close, reports, users, audit, backup |
| `nolima_acc/licensing.py` | Licence keys, Machine ID, expiry / reminder / grace / read-only states, clock-tamper check |
| `nolima_acc/plans.py` | **Packages and prices** (Business, Enterprise) and billing cycles; edit here |
| `nolima_acc/coa_templates.py` | Charts of accounts for 8 industries (hospitality, retail, services, NGO, manufacturing, agriculture, school, general) |
| `nolima_acc/ui/` | Desktop interface: glass dashboard, colour icon sidebar, colour tabs, rounded controls |
| `nolima_acc/updater.py` | Signed remote updates |
| `release_update.bat` | Build, sign and publish an update to all customers |
| `license_generator/` | **Your private tool** for issuing and renewing keys. Never give this to customers |
| `NolimaAccounting.spec`, `build/` | PyInstaller spec, one-click Windows build script, Inno Setup installer |
| `.github/workflows/` | Builds the installer on GitHub and publishes releases for the update checker |
| `INSTALL.md` | Building, installing on customer PCs, moving to a new PC, upgrading |
| `tests/test_core.py` | Engine and licensing tests |

## First-time setup (do this once, on your own PC)

1. Double-click `build\build_windows.bat` (does steps 2 and 3 for you), or manually:
2. Run the generator once: `python license_generator/nolima_license_generator.py`
   - It creates your signing key in `%USERPROFILE%\NolimaLicenseVault\` and writes the matching
     public key into `nolima_acc/license_pubkey.py`.
   - **Back up the vault folder** (flash disk + cloud). Lose it and you cannot renew existing customers.
3. Build the installer: double-click `build\build_windows.bat` → `Output\NolimaAccounting-Setup-1.3.0.exe`
   (or let GitHub build it; see **INSTALL.md**, which also covers installing at customers and moving to a new PC)

Commit `license_pubkey.py` to GitHub; never commit the vault folder.

## Selling and renewing licences

1. Install at the customer. On first start it shows the **Machine ID** (or they start a 14-day trial).
2. In the generator: *New customer* → enter name, phone and Machine ID.
3. When they pay: select the customer → *Issue / renew licence* → choose package, billing cycle and
   number of cycles → *Generate key*. The key is copied to the clipboard and a ready WhatsApp/email
   message is shown.
4. The customer pastes it in **Settings → Licence → Enter renewal key**.

Renewals start from the previous expiry date, so paying early never loses days. The generator's main
screen shows every customer's expiry, days left, customers due within 14 days, monthly recurring
revenue and money collected this month; *Export payments CSV* gives your licence income register.

Command-line alternative:

```
python license_generator/nolima_license_generator.py issue --customer "Thunzi Executive Lodge" ^
    --machine 8536-9313-C031-8B9A --plan business --cycle monthly --periods 1 --ref "DEP-001"
python license_generator/nolima_license_generator.py due
```

### Packages (from `plans.py`)

| Package | MWK / month | Users | Modules |
| --- | --- | --- | --- |
| Business | 85,000 | 6 | + purchases, bank reconciliation, inventory, departments |
| Enterprise | 150,000 | Unlimited | + multiple companies, audit trail viewer |

Billing cycles: monthly; quarterly (5% off); annual (pay 10 months, get 12).

### What happens at expiry

| Days relative to expiry | State | Customer experience |
| --- | --- | --- |
| more than 14 before | Active | Normal |
| 14 before to expiry | Reminder | Amber banner with days left |
| up to 7 after | Grace | Red banner, still fully working |
| more than 7 after | Read-only | View, print and export only; no posting until a key is entered |

Keys are signed with Ed25519 (cannot be edited or forged), bound to the Machine ID, and the app
detects the computer clock being set back.

## Running from source

```
python main.py                  # the application
python tests/test_core.py       # tests
```

Data lives in `C:\ProgramData\NolimaAccounting\` (company files, licence, backups, exports).
Set `NOLIMA_ACC_DATA` to use another folder (useful for demos).

## Remote updates

Customers' copies check for a new version at start-up and every 6 hours. When one is found they see
*"Nolima Accounting x.y.z is ready"* with your release notes; one click downloads it, checks it and
installs it silently, keeping their data and licence, and reopens the program.

Every update is signed with your private key (the same vault as licences). The program checks the
signature and the installer's SHA-256 before installing, and refuses anything else. A hacked GitHub
account or a corrupted download cannot put software on a customer's computer.

**To publish an update**

1. Raise `__version__` in `nolima_acc/__init__.py` (e.g. `1.0.1`).
2. Write what changed in `release_notes.txt` (shown to customers).
3. Double-click `release_update.bat`. It builds, signs and publishes the release to GitHub
   (needs the [GitHub CLI](https://cli.github.com), signed in once with `gh auth login`). It asks whether
   the update is **required**; required updates cannot be postponed by the customer.

The repository `Mau134/nolima-accounting` must be public so customers' copies can read the releases
(change `UPDATE_REPO` in `config.py` otherwise, or host `update.json` on your own website with
`UPDATE_FEED_URL`). Customers can also check manually in **Settings > About > Check for updates**.

## Current limits and next steps

- v1 runs on **one computer** (several users sign in on it with their own logins and roles).
  Networked access from several PCs is the next step: reuse Nolima Store's client-server RPC layer
  around `services.Books`, which the UI already talks to exclusively.
- Payroll (PAYE, pension), fixed-asset register with automatic depreciation, and budgets are not yet
  included; depreciation is posted with a manual journal.
