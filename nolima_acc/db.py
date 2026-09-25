"""SQLite storage for a Nolima Accounting company file (*.nacc)."""
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE, full_name TEXT,
    role TEXT NOT NULL, pw_hash TEXT NOT NULL, salt TEXT NOT NULL, active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY, ts TEXT DEFAULT CURRENT_TIMESTAMP, username TEXT, action TEXT,
    entity TEXT, entity_id INTEGER, details TEXT);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('asset','liability','equity','income','expense')),
    subtype TEXT DEFAULT 'other', description TEXT, active INTEGER DEFAULT 1, system INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS departments (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, active INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY, date TEXT NOT NULL, ref TEXT, memo TEXT, source_type TEXT NOT NULL,
    source_id INTEGER, created_by TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, reversal_of INTEGER);

CREATE TABLE IF NOT EXISTS journal_lines (
    id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES journal_entries(id),
    account_id INTEGER NOT NULL REFERENCES accounts(id), department_id INTEGER REFERENCES departments(id),
    debit REAL DEFAULT 0, credit REAL DEFAULT 0, description TEXT, rec_id INTEGER);
CREATE INDEX IF NOT EXISTS ix_lines_account ON journal_lines(account_id);
CREATE INDEX IF NOT EXISTS ix_lines_entry ON journal_lines(entry_id);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('customer','supplier')), name TEXT NOT NULL,
    phone TEXT, email TEXT, address TEXT, tpin TEXT, active INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT NOT NULL, kind TEXT DEFAULT 'service',
    unit TEXT DEFAULT 'each', sale_price REAL DEFAULT 0, cost_price REAL DEFAULT 0, qty_on_hand REAL DEFAULT 0,
    income_account_id INTEGER REFERENCES accounts(id), expense_account_id INTEGER REFERENCES accounts(id),
    vatable INTEGER DEFAULT 1, reorder_level REAL DEFAULT 0, active INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('sale','bill')), number TEXT NOT NULL,
    contact_id INTEGER REFERENCES contacts(id), date TEXT NOT NULL, due_date TEXT, status TEXT DEFAULT 'open',
    subtotal REAL DEFAULT 0, vat REAL DEFAULT 0, total REAL DEFAULT 0, amount_paid REAL DEFAULT 0,
    memo TEXT, reference TEXT, entry_id INTEGER, created_by TEXT, UNIQUE(kind, number));

CREATE TABLE IF NOT EXISTS invoice_lines (
    id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id), item_id INTEGER REFERENCES items(id),
    description TEXT, qty REAL DEFAULT 1, unit_price REAL DEFAULT 0, vat_rate REAL DEFAULT 0,
    account_id INTEGER REFERENCES accounts(id), department_id INTEGER REFERENCES departments(id),
    net REAL DEFAULT 0, vat REAL DEFAULT 0, unit_cost REAL DEFAULT 0);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('receipt','payment')), number TEXT,
    contact_id INTEGER REFERENCES contacts(id), date TEXT NOT NULL, account_id INTEGER REFERENCES accounts(id),
    amount REAL NOT NULL, method TEXT, reference TEXT, memo TEXT, entry_id INTEGER, created_by TEXT,
    status TEXT DEFAULT 'posted');

CREATE TABLE IF NOT EXISTS allocations (
    id INTEGER PRIMARY KEY, payment_id INTEGER REFERENCES payments(id), invoice_id INTEGER REFERENCES invoices(id),
    amount REAL NOT NULL);

CREATE TABLE IF NOT EXISTS stock_moves (
    id INTEGER PRIMARY KEY, item_id INTEGER REFERENCES items(id), date TEXT, qty REAL, unit_cost REAL,
    source_type TEXT, source_id INTEGER, memo TEXT);

CREATE TABLE IF NOT EXISTS reconciliations (
    id INTEGER PRIMARY KEY, account_id INTEGER REFERENCES accounts(id), statement_date TEXT,
    statement_balance REAL, created_by TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""


def connect(path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), detect_types=0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    cur = conn.execute("SELECT value FROM settings WHERE key='schema_version'")
    if cur.fetchone() is None:
        conn.execute("INSERT INTO settings(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
        conn.commit()
    return conn
