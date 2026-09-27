"""Application shell: licence activation, company selection, setup wizard, login and main window."""
import threading
import tkinter as tk
import webbrowser
from datetime import date
from pathlib import Path
from tkinter import ttk

from .. import config as C, licensing, plans
from ..coa_templates import INDUSTRY
from ..services import AccError, Books
from . import theme
from .theme import f, money
from .widgets import Dialog, Table, confirm, draw_logo, error, info
from . import pages as P

NAV = [
    ("Dashboard", P.DashboardPage, None),
    ("Sales", P.SalesPage, None),
    ("Purchases", P.PurchasesPage, "purchases"),
    ("Banking", P.BankingPage, None),
    ("Items", P.ItemsPage, None),
    ("Accounting", P.AccountingPage, None),
    ("Reports", P.ReportsPage, None),
    ("Settings", P.SettingsPage, None),
]


def companies():
    d = C.data_dir() / "companies"
    return sorted(d.glob("*.nacc"))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        theme.apply(root)
        root.title(C.APP_NAME)
        root.geometry("1360x820")
        root.minsize(1100, 680)
        self.lic = licensing.LicenseManager(C.data_dir())
        self.books = None
        self.frame = None
        self.pages = {}
        self.start()

    # ------------------------------------------------------------ helpers
    def lic_status(self):
        return self.lic.status()

    def clear(self):
        if self.frame is not None:
            self.frame.destroy()
        self.frame = ttk.Frame(self.root)
        self.frame.pack(fill="both", expand=True)
        return self.frame

    def brand_panel(self, parent, subtitle=""):
        from . import art
        side = tk.Canvas(parent, width=440, highlightthickness=0, bd=0, bg=C.NAVY)
        side.pack(side="left", fill="y")
        state = {"size": None, "img": None}

        def draw(_e=None):
            w, h = side.winfo_width(), side.winfo_height()
            if w < 10 or h < 10 or state["size"] == (w, h):
                return
            state["size"] = (w, h)
            box = (40, h * 0.5 - 190, w - 40, h * 0.5 + 150)
            state["img"] = art.ImageTk.PhotoImage(art.compose_glass(w, h, (tuple(int(v) for v in box),), radius=24))
            side.delete("all")
            side.create_image(0, 0, image=state["img"], anchor="nw")
            cx = w / 2
            draw_logo(side, cx - 29, box[1] + 44, 1.55)
            side.create_text(cx, box[1] + 158, text="Nolima Accounting", fill="white", font=f(22, "bold"))
            side.create_text(cx, box[1] + 192, text=subtitle or "Professional accounting for every business",
                             fill="#B9E6D4", font=f(10))
            for i, (t, col) in enumerate((("Sales and invoicing", "#34D399"), ("Banking and VAT", "#60A5FA"),
                                          ("Reports in one click", "#FBBF24"))):
                y = box[1] + 238 + i * 30
                side.create_oval(cx - 92, y - 5, cx - 82, y + 5, fill=col, outline="")
                side.create_text(cx - 72, y, text=t, anchor="w", fill="#E2E8F0", font=f(10))
            side.create_text(cx, h - 40, text=f"Version {C.VERSION}  \u00b7  {C.VENDOR}\n{C.VENDOR_PHONE}  \u00b7  "
                                              f"{C.VENDOR_EMAIL}", fill="#9FB3C8", font=f(8), justify="center")
        side.bind("<Configure>", draw)
        right = ttk.Frame(parent, padding=60)
        right.pack(side="left", fill="both", expand=True)
        return right

    # ------------------------------------------------------------ startup flow
    def start(self):
        st = self.lic_status()
        if st.state == licensing.NONE:
            self.activation_screen()
        else:
            self.company_screen()

    def activation_screen(self):
        right = self.brand_panel(self.clear(), "Activate your copy")
        ttk.Label(right, text="Activate Nolima Accounting", style="H1.TLabel").pack(anchor="w")
        ttk.Label(right, text="Send this computer's Machine ID to Nolima Tech Consultants to receive your licence key.",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 18))
        box = ttk.Frame(right, style="Panel.TFrame", padding=28)
        box.pack(fill="x")
        ttk.Label(box, text="MACHINE ID", style="CardMuted.TLabel").pack(anchor="w")
        mid = licensing.this_machine_id()
        row = ttk.Frame(box, style="Card.TFrame")
        row.pack(anchor="w", pady=(2, 14))
        ttk.Label(row, text=mid, style="Card.TLabel", font=f(16, "bold")).pack(side="left")
        ttk.Button(row, text="Copy", command=lambda: (self.root.clipboard_clear(), self.root.clipboard_append(mid),
                                                     info(self.root, "Machine ID copied."))).pack(side="left", padx=12)
        ttk.Label(box, text="LICENCE KEY", style="CardMuted.TLabel").pack(anchor="w")
        txt = tk.Text(box, height=4, width=70, font=("Consolas", 10), relief="solid", bd=1)
        txt.pack(fill="x", pady=(2, 12))

        def activate():
            try:
                i = self.lic.install(txt.get("1.0", "end"))
                info(self.root, f"Activated: {i.plan_name} package, valid until {i.expires:%d %B %Y}.")
                self.company_screen()
            except licensing.LicenseError as exc:
                error(self.root, exc)
        bar = ttk.Frame(box, style="Card.TFrame")
        bar.pack(anchor="w")
        ttk.Button(bar, text="Activate", style="Primary.TButton", command=activate).pack(side="left")
        ttk.Button(bar, text=f"Start {plans.TRIAL_DAYS}-day trial",
                   command=lambda: (self.lic.start_trial(), self.company_screen())).pack(side="left", padx=8)
        pk = "\n".join(f"{p['name']}:  MWK {p['monthly']:,} per month  \u00b7  "
                       f"{'unlimited' if not p['users'] else p['users']} users" for p in plans.PLANS.values())
        ttk.Label(right, text="Packages\n" + pk, style="Muted.TLabel", justify="left").pack(anchor="w", pady=20)

    def company_screen(self):
        files = companies()
        if not files:
            self.setup_screen(C.data_dir() / "companies" / C.DEFAULT_COMPANY_FILE)
            return
        self.login_screen(files)

    def setup_screen(self, path: Path):
        right = self.brand_panel(self.clear(), "Set up your company")
        ttk.Label(right, text="Set up your company", style="H1.TLabel").pack(anchor="w")
        ttk.Label(right, text="This takes a minute. Everything can be changed later in Settings.",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 14))
        box = ttk.Frame(right, style="Panel.TFrame", padding=28)
        box.pack(fill="x")
        v = {k: tk.StringVar() for k in ("name", "industry", "address", "phone", "email", "tpin", "vat", "fy",
                                         "admin_name", "user", "pw", "pw2")}
        v["industry"].set(list(INDUSTRY)[0])
        v["vat"].set("17.5")
        v["fy"].set("January")
        v["user"].set(C.DEFAULT_ADMIN_USER)
        v["pw"].set(C.DEFAULT_ADMIN_PASSWORD)
        v["pw2"].set(C.DEFAULT_ADMIN_PASSWORD)
        months = [date(2000, i, 1).strftime("%B") for i in range(1, 13)]
        fields = [("name", "Company name", None), ("industry", "Industry", list(INDUSTRY)),
                  ("address", "Address", None), ("phone", "Phone", None), ("email", "Email", None),
                  ("tpin", "TPIN", None), ("vat", "VAT rate (%)", None), ("fy", "Financial year starts", months),
                  ("admin_name", "Your full name", None), ("user", "Administrator username", None),
                  ("pw", "Password", None), ("pw2", "Confirm password", None)]
        for i, (k, label, opts) in enumerate(fields):
            r, c = divmod(i, 2)
            ttk.Label(box, text=label, style="CardMuted.TLabel").grid(row=r * 2, column=c, sticky="w", padx=8)
            if opts:
                w = ttk.Combobox(box, textvariable=v[k], values=opts, state="readonly", width=36)
            else:
                w = ttk.Entry(box, textvariable=v[k], width=38, show="\u2022" if k.startswith("pw") else "")
            w.grid(row=r * 2 + 1, column=c, sticky="ew", padx=8, pady=(0, 10))

        def create():
            try:
                if v["pw"].get() != v["pw2"].get():
                    raise AccError("Passwords do not match.")
                books = Books(path, self.lic_status)
                books.setup_company(v["name"].get(), v["industry"].get(), v["user"].get(), v["pw"].get(),
                                    v["admin_name"].get(), v["address"].get(), v["phone"].get(), v["email"].get(),
                                    v["tpin"].get(), float(v["vat"].get() or 0), months.index(v["fy"].get()) + 1)
                books.login(v["user"].get(), v["pw"].get())
                try:
                    books.save_contact("customer", "Walk-in Customer")
                except AccError:
                    pass
                books.login(v["user"].get(), v["pw"].get())
                self.books = books
                self.main_window()
            except (AccError, ValueError) as exc:
                if path.exists():
                    try:
                        b = Books(path)
                        done = b.is_setup()
                        b.close()
                        if not done:
                            path.unlink()
                    except Exception:
                        pass
                error(self.root, exc)
        ttk.Label(right, text=f"Default administrator login: {C.DEFAULT_ADMIN_USER} / {C.DEFAULT_ADMIN_PASSWORD}. "
                              "You will be asked to change the password after signing in.",
                  style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Button(right, text="Create company", style="Primary.TButton", command=create).pack(anchor="w", pady=14)
        if companies():
            ttk.Button(right, text="Back", command=self.company_screen).pack(anchor="w")

    def login_screen(self, files):
        right = self.brand_panel(self.clear())
        ttk.Label(right, text="Sign in", style="H1.TLabel").pack(anchor="w")
        st = self.lic_status()
        ttk.Label(right, text=st.message, style="Muted.TLabel", wraplength=520).pack(anchor="w", pady=(4, 18))
        box = ttk.Frame(right, style="Panel.TFrame", padding=30)
        box.pack(anchor="w")
        multi = st.has("multi_company")
        comp = tk.StringVar()
        names = {}
        for p in files:
            try:
                b = Books(p)
                names[b.setting("company_name", p.stem)] = p
                b.close()
            except Exception:
                names[p.stem] = p
        comp.set(next(iter(names)))
        if multi or len(names) > 1:
            ttk.Label(box, text="COMPANY", style="CardMuted.TLabel").pack(anchor="w")
            ttk.Combobox(box, textvariable=comp, values=list(names) if multi else [comp.get()], state="readonly",
                         width=36).pack(anchor="w", pady=(2, 12))
        else:
            ttk.Label(box, text=comp.get(), style="H2.TLabel").pack(anchor="w", pady=(0, 12))
        user, pw = tk.StringVar(), tk.StringVar()
        ttk.Label(box, text="USERNAME", style="CardMuted.TLabel").pack(anchor="w")
        ue = ttk.Entry(box, textvariable=user, width=38)
        ue.pack(anchor="w", pady=(2, 12))
        ttk.Label(box, text="PASSWORD", style="CardMuted.TLabel").pack(anchor="w")
        pe = ttk.Entry(box, textvariable=pw, width=38, show="\u2022")
        pe.pack(anchor="w", pady=(2, 16))

        def go(_e=None):
            try:
                books = Books(names[comp.get()], self.lic_status)
                books.login(user.get(), pw.get())
                self.books = books
                self.main_window()
            except AccError as exc:
                error(self.root, exc)
        ttk.Button(box, text="Sign in", style="Primary.TButton", command=go).pack(anchor="w")
        pe.bind("<Return>", go)
        ue.focus_set()
        links = ttk.Frame(right)
        links.pack(anchor="w", pady=16)
        if multi:
            n = len(files) + 1
            ttk.Button(links, text="New company", command=lambda: self.setup_screen(
                C.data_dir() / "companies" / f"company{n}.nacc")).pack(side="left")
        ttk.Button(links, text="Licence", command=self.enter_key).pack(side="left", padx=6)

    # ------------------------------------------------------------ main window
    def main_window(self):
        root = self.clear()
        self.root.title(f"{C.APP_NAME} \u2014 {self.books.setting('company_name')}")
        from . import art
        self.art = art
        side = tk.Frame(root, bg=C.NAVY, width=240)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        head = tk.Frame(side, bg=C.NAVY)
        head.pack(fill="x", pady=(20, 24), padx=18)
        cv = tk.Canvas(head, bg=C.NAVY, highlightthickness=0, width=40, height=58)
        cv.pack(side="left")
        draw_logo(cv, 1, 2, 1.0)
        t = tk.Frame(head, bg=C.NAVY)
        t.pack(side="left", padx=10)
        tk.Label(t, text="Nolima", bg=C.NAVY, fg="white", font=f(16, "bold")).pack(anchor="w")
        tk.Label(t, text="ACCOUNTING", bg=C.NAVY, fg="#6EE7B7", font=f(8, "bold")).pack(anchor="w")
        tk.Label(side, text="MENU", bg=C.NAVY, fg="#5F7A96", font=f(8, "bold")).pack(anchor="w", padx=24, pady=(0, 6))
        self.nav_btns = {}
        self._nav_pills = (art.photo(art.rounded(208, 48, 14, "#1E4470")),
                           art.photo(art.rounded(208, 48, 14, "#16365A")))
        st = self.lic_status()
        for name, _cls, module in NAV:
            locked = bool(module and not st.has(module))
            c = tk.Canvas(side, width=240, height=52, bg=C.NAVY, highlightthickness=0, cursor="hand2")
            c.pack(fill="x")
            bgid = c.create_image(16, 2, image=self._nav_pills[0], anchor="nw", state="hidden")
            c.create_image(28, 26, image=art.badge(name, 32) if not locked else
                           art.badge(name, 32, ("#475569", "#334155")), anchor="w")
            txt = c.create_text(72, 26, text=name, anchor="w", fill="#D5E1EC" if not locked else "#6F869E",
                                font=f(11))
            if locked:
                c.create_text(212, 26, text="PRO", anchor="e", fill="#FBBF24", font=f(7, "bold"))
            self.nav_btns[name] = {"canvas": c, "bg": bgid, "txt": txt, "locked": locked}
            c.bind("<Button-1>", lambda e, n=name, l=locked: self.upgrade_msg() if l else self.show_page(n))
            c.bind("<Enter>", lambda e, n=name: self._nav_hover(n, True))
            c.bind("<Leave>", lambda e, n=name: self._nav_hover(n, False))
        u = self.books.user
        foot = tk.Frame(side, bg=C.NAVY)
        foot.pack(side="bottom", fill="x", padx=18, pady=16)
        tk.Label(foot, text=u["full_name"] or u["username"], bg=C.NAVY, fg="white", font=f(10, "bold")).pack(anchor="w")
        tk.Label(foot, text=u["role"], bg=C.NAVY, fg="#8CA3BA", font=f(9)).pack(anchor="w")
        lo = tk.Label(foot, text="Sign out", bg=C.NAVY, fg="#9FD4BF", font=f(9, "underline"), cursor="hand2")
        lo.pack(anchor="w", pady=(6, 0))
        lo.bind("<Button-1>", lambda e: self.sign_out())

        main = ttk.Frame(root)
        main.pack(side="left", fill="both", expand=True)
        self.banner = tk.Frame(main, bg=C.WARNING)
        self.banner_lbl = tk.Label(self.banner, text="", bg=C.WARNING, fg="white", font=f(10, "bold"), pady=7)
        self.banner_lbl.pack(side="left", padx=16)
        self.banner_btn = tk.Label(self.banner, text="Enter renewal key \u203a", bg=C.WARNING, fg="white",
                                   font=f(10, "underline"), cursor="hand2")
        self.banner_btn.pack(side="right", padx=16)
        self.banner_btn.bind("<Button-1>", lambda e: self.enter_key())
        self.container = ttk.Frame(main)
        self.container.pack(fill="both", expand=True)
        self.pages = {}
        self.current = None
        self.update_banner()
        self.show_page("Dashboard")
        if getattr(self.books, "using_default_password", False):
            self.root.after(500, self.force_password_change)
        self.root.after(4000, self.start_update_checks)

    def _nav_hover(self, name, on):
        b = self.nav_btns[name]
        if name == self.current or b["locked"]:
            return
        c = b["canvas"]
        c.itemconfigure(b["bg"], image=self._nav_pills[1], state="normal" if on else "hidden")

    def update_banner(self):
        st = self.lic_status()
        if st.state in (licensing.REMINDER, licensing.GRACE, licensing.READONLY, licensing.TRIAL):
            col = C.DANGER if st.state in (licensing.GRACE, licensing.READONLY) else C.WARNING
            for w in (self.banner, self.banner_lbl, self.banner_btn):
                w.configure(bg=col)
            self.banner_lbl.configure(text=st.message)
            self.banner.pack(fill="x", before=self.container)
        else:
            self.banner.pack_forget()

    def force_password_change(self):
        from .widgets import FormDialog
        def change(v):
            if v["new"] != v["new2"]:
                raise AccError("Passwords do not match.")
            if v["new"] == C.DEFAULT_ADMIN_PASSWORD:
                raise AccError("Choose a password different from the default one.")
            self.books.change_own_password(C.DEFAULT_ADMIN_PASSWORD, v["new"])
            return True
        res = FormDialog(self.root, "Change the default password", [
            ("new", "New password", "password"), ("new2", "Confirm new password", "password")],
            change, ok_text="Change password").show()
        if res:
            self.books.using_default_password = False
            info(self.root, "Password changed. Use the new password next time you sign in.")
        else:
            info(self.root, "You are still using the default password. You will be asked again at next sign-in.")

    def upgrade_msg(self):
        info(self.root, "This module is not included in your licence package.\n\nUpgrade to Business or Enterprise: "
                        f"call {C.VENDOR_PHONE} or email {C.VENDOR_EMAIL}.")

    def show_page(self, name):
        if name not in self.pages:
            cls = next(c for n, c, _ in NAV if n == name)
            self.pages[name] = cls(self.container, self)
        for n, p in self.pages.items():
            p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        for n, b in self.nav_btns.items():
            if b["locked"]:
                continue
            c, active = b["canvas"], n == name
            c.itemconfigure(b["bg"], image=self._nav_pills[0], state="normal" if active else "hidden")
            c.itemconfigure(b["txt"], fill="white" if active else "#D5E1EC", font=f(11, "bold") if active else f(11))
        self.current = name
        try:
            self.pages[name].refresh()
        except AccError as exc:
            error(self.root, exc)

    def refresh(self):
        self.update_banner()
        if self.current:
            self.pages[self.current].refresh()

    def open_dialog(self, cls, *args):
        try:
            res = cls(self.root, self.books, *args).show()
        except AccError as exc:
            error(self.root, exc)
            return None
        if res:
            self.refresh()
        return res

    def show_entry(self, entry_id):
        e = self.books.one("SELECT * FROM journal_entries WHERE id=?", (entry_id,))
        if not e:
            return
        d = Dialog(self.root, f"Journal entry #{entry_id}", width=820)
        ttk.Label(d.body, text=f"{e['date']}   {e['ref'] or ''}   {e['memo']}", style="H2.TLabel").pack(anchor="w")
        ttk.Label(d.body, text=f"Source: {e['source_type']}   Posted by {e['created_by']} at {e['created_at']}",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(2, 8))
        t = Table(d.body, [("a", "Account", 300, "w"), ("dep", "Department", 120, "w"), ("de", "Details", 180, "w"),
                           ("dr", "Debit", 100, "e"), ("cr", "Credit", 100, "e")], height=8)
        t.pack(fill="both", expand=True)
        lines = self.books.entry_lines(entry_id)
        t.set_rows([[f"{l['code']}  {l['account']}", l["department"] or "", l["description"],
                     money(l["debit"], True), money(l["credit"], True)] for l in lines])
        ttk.Button(d.buttons, text="Close", command=d.destroy).pack(side="right")
        d.show()

    def enter_key(self):
        d = Dialog(self.root, "Enter licence key", width=620)
        ttk.Label(d.body, text=f"Machine ID:  {licensing.this_machine_id()}", style="H2.TLabel").pack(anchor="w")
        ttk.Label(d.body, text="Paste the licence or renewal key you received from Nolima Tech Consultants.",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(4, 8))
        txt = tk.Text(d.body, height=5, width=70, font=("Consolas", 10), relief="solid", bd=1)
        txt.pack(fill="x")

        def ok():
            try:
                i = self.lic.install(txt.get("1.0", "end"))
            except licensing.LicenseError as exc:
                error(d, exc)
                return
            info(d, f"Licence updated: {i.plan_name} package, valid until {i.expires:%d %B %Y}.\n"
                    "Restart Nolima Accounting if modules changed.")
            d.result = True
            d.destroy()
        ttk.Button(d.buttons, text="Apply key", style="Primary.TButton", command=ok).pack(side="right")
        ttk.Button(d.buttons, text="Cancel", command=d.destroy).pack(side="right", padx=8)
        if d.show():
            if self.books:
                self.refresh()
            else:
                self.company_screen()

    def sign_out(self):
        if self.books:
            self.books.close()
        self.books = None
        self.company_screen()

    def restore_backup(self, backup_file):
        path = self.books.path
        self.books.close()
        try:
            Books.restore(backup_file, path)
            info(self.root, "Backup restored. Please sign in again.")
        except AccError as exc:
            error(self.root, exc)
        self.books = None
        self.company_screen()

    # ------------------------------------------------------------ updates
    def start_update_checks(self):
        """Check now in the background, then every few hours while the program is open."""
        self._update_dismissed = getattr(self, "_update_dismissed", None)

        def work():
            try:
                from .. import updater
                found = updater.check()
            except Exception:
                found = None
            if found:
                self.root.after(0, lambda: self._offer_update(found))
        threading.Thread(target=work, daemon=True).start()
        self.root.after(int(C.UPDATE_CHECK_HOURS * 3600 * 1000), self.start_update_checks)

    def _offer_update(self, upd, manual=False):
        if not manual and not upd.mandatory and self._update_dismissed == upd.version:
            return
        if getattr(self, "_update_open", False):
            return
        self._update_open = True
        try:
            UpdateDialog(self.root, self, upd).show()
        finally:
            self._update_open = False

    def check_updates(self):
        from .. import updater
        try:
            found = updater.check()
        except updater.UpdateError as exc:
            error(self.root, exc)
            return
        if found:
            self._offer_update(found, manual=True)
        else:
            info(self.root, f"You have the latest version ({C.VERSION}).")

    def quit_for_update(self):
        if self.books:
            self.books.close()
        self.root.destroy()


class UpdateDialog(Dialog):
    def __init__(self, parent, app, upd):
        super().__init__(parent, "Update available", width=560)
        self.app, self.upd = app, upd
        from . import art
        top = ttk.Frame(self.body, style="Card.TFrame")
        top.pack(fill="x")
        tk.Label(top, image=art.badge("Dashboard", 48, ("#34D399", "#059669"), "down"), bg=C.CARD).pack(side="left")
        t = ttk.Frame(top, style="Card.TFrame")
        t.pack(side="left", padx=14)
        ttk.Label(t, text=f"Nolima Accounting {upd.version} is ready", style="H2.TLabel").pack(anchor="w")
        size = f" \u00b7 {upd.size / 1048576:.0f} MB" if upd.size else ""
        ttk.Label(t, text=f"You have version {C.VERSION}{size}", style="CardMuted.TLabel").pack(anchor="w")
        if upd.mandatory:
            ttk.Label(self.body, text="This is a required update from Nolima Tech Consultants.",
                      style="Card.TLabel", foreground=C.WARNING).pack(anchor="w", pady=(12, 0))
        ttk.Label(self.body, text="What's new", style="CardMuted.TLabel").pack(anchor="w", pady=(14, 4))
        notes = tk.Text(self.body, height=7, width=62, wrap="word", relief="flat", bg="#F4F7FA", font=f(10),
                        padx=10, pady=8)
        notes.insert("1.0", upd.notes or "Improvements and fixes.")
        notes.configure(state="disabled")
        notes.pack(fill="x")
        ttk.Label(self.body, text="Your data and licence are kept. The program closes, updates and opens again.",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(10, 4))
        self.bar = ttk.Progressbar(self.body, mode="determinate", maximum=100)
        self.status = ttk.Label(self.body, text="", style="CardMuted.TLabel")
        self.install_btn = ttk.Button(self.buttons, text="Install now", style="Primary.TButton", command=self.start)
        self.install_btn.pack(side="right")
        if not upd.mandatory:
            self.later_btn = ttk.Button(self.buttons, text="Later", command=self.later)
            self.later_btn.pack(side="right", padx=8)
        else:
            self.protocol("WM_DELETE_WINDOW", lambda: None)
            self.unbind("<Escape>")
        self._cancel = False

    def later(self):
        self.app._update_dismissed = self.upd.version
        self.destroy()

    def start(self):
        from .. import updater
        self.install_btn.state(["disabled"])
        if hasattr(self, "later_btn"):
            self.later_btn.state(["disabled"])
        self.bar.pack(fill="x", pady=(8, 2))
        self.status.pack(anchor="w")
        self.status.configure(text="Downloading...")

        def progress(done, total):
            pct = done * 100 / total if total else 0
            self.after(0, lambda: (self.bar.configure(value=pct),
                                   self.status.configure(text=f"Downloading... {done / 1048576:.1f} MB"
                                                              + (f" of {total / 1048576:.1f} MB" if total else ""))))

        def work():
            try:
                path = updater.download(self.upd, progress)
                self.after(0, lambda: self.finish(path))
            except updater.UpdateError as exc:
                self.after(0, lambda: self.failed(exc))
        threading.Thread(target=work, daemon=True).start()

    def finish(self, path):
        from .. import updater
        self.status.configure(text="Verified. Installing...")
        try:
            updater.install(path)
        except updater.UpdateError as exc:
            self.failed(exc)
            return
        self.destroy()
        self.app.quit_for_update()

    def failed(self, exc):
        error(self, exc)
        self.install_btn.state(["!disabled"])
        if hasattr(self, "later_btn"):
            self.later_btn.state(["!disabled"])
        self.status.configure(text="")


def run():
    root = tk.Tk()
    try:
        from ..config import resource_path
        ico = resource_path("assets", "nolima.ico")
        if ico.exists():
            root.iconbitmap(str(ico))
    except Exception:
        pass
    App(root)
    root.mainloop()
