# Building and installing Nolima Accounting on other computers

## 1. Make the installer (once per version, on your PC)

You need Windows 10/11, Python 3.10+ (tick "Add to PATH" when installing) and
[Inno Setup 6](https://jrsoftware.org/isdl.php).

1. Double-click `build\build_windows.bat`. It installs everything it needs, creates your licence
   signing key the first time (in `%USERPROFILE%\NolimaLicenseVault`; **back this folder up**), runs the
   tests, packages the program and builds the installer:

   `Output\NolimaAccounting-Setup-1.3.0.exe`

2. To issue keys, double-click `run_generator.bat` in the project folder.

That single file is all you carry to a customer (flash disk, WhatsApp, Google Drive). Python is **not**
needed on the customer's computer; everything is inside the installer.

### Or let GitHub build it

Push the project to `github.com/Mau134/nolima-accounting` (with `license_pubkey.py` committed, never the
vault). The workflow in `.github/workflows/build-windows.yml` builds a test installer on every push
(download it from the run's *Artifacts*). Updates for customers are published from your PC with
`release_update.bat`, because they must be signed with your private key (see README, *Remote updates*).

## 2. Install at the customer

1. Run `NolimaAccounting-Setup-x.y.z.exe` as administrator, then Next > Install > Finish.
2. Nolima Accounting opens on the activation screen showing the **Machine ID**
   (e.g. `8536-9313-C031-8B9A`). Copy it.
3. In the Licence Generator: add the customer with that Machine ID, choose the package and
   *Issue / renew licence*. Paste the key into the activation screen and click *Activate*
   (or *Start 14-day trial* while waiting for payment).
4. Set up the company. The administrator login is pre-filled as `admin` / `admin123`; the program asks for a
   new password after the first sign-in. Then add users.

Each computer has its own Machine ID, so **each computer needs its own key**. A key copied to another PC
is rejected with a message showing both IDs.

Requirements: Windows 10 or 11, 64-bit. About 60 MB of disk.

## 3. Where the data lives

`C:\ProgramData\NolimaAccounting\`: `companies\` (the books), `backups\`, `exports\` and the licence.
Uninstalling or upgrading never deletes this folder. Every Windows user on the PC shares the same books.

## 4. Moving a customer to a new computer

1. On the old PC: *Settings > Backup and restore > Back up to folder...* onto a flash disk.
2. Install on the new PC and note its Machine ID. Close the program at the activation screen.
3. Copy the backup file into `C:\ProgramData\NolimaAccounting\companies\` on the new PC and rename it
   `company.nacc`.
4. Issue a free replacement key for the new Machine ID (same package; the start date carries on from the
   current expiry) and activate.

## 5. Upgrading customers

Publish with `release_update.bat` and every customer is offered the update automatically. To upgrade one PC by
hand, run the newer Setup.exe over the old installation. The licence and data are kept either way.
