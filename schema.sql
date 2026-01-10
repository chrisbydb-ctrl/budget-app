PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS owners (
  id TEXT PRIMARY KEY,
  system_key TEXT UNIQUE NOT NULL,       -- shared | person_1 | person_2
  display_name TEXT NOT NULL,
  sort_order INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
  id TEXT PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bills (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES owners(id),
  name TEXT NOT NULL,
  due_day INTEGER,                      -- 1..31
  default_amount REAL,                  -- planned
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES owners(id),
  name TEXT NOT NULL,
  type TEXT NOT NULL,                   -- CREDIT_CARD | LOAN
  apr REAL,
  credit_limit REAL,                    -- null for loans
  start_balance REAL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
  id TEXT PRIMARY KEY,
  txn_date TEXT NOT NULL,               -- YYYY-MM-DD
  owner_id TEXT NOT NULL REFERENCES owners(id),
  category_id TEXT NOT NULL REFERENCES categories(id),
  description TEXT,
  amount REAL NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS account_snapshots (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  month TEXT NOT NULL,                  -- YYYY-MM
  balance REAL NOT NULL,
  payment REAL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(account_id, month)
);

CREATE TABLE IF NOT EXISTS income (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES owners(id),
  month TEXT NOT NULL,                  -- YYYY-MM
  amount REAL NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(owner_id, month)
);

CREATE TABLE IF NOT EXISTS budgets (
  id TEXT PRIMARY KEY,
  month TEXT NOT NULL,                  -- YYYY-MM
  owner_id TEXT NOT NULL REFERENCES owners(id),
  category_id TEXT NOT NULL REFERENCES categories(id),
  planned_amount REAL NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(month, owner_id, category_id)
);

CREATE TABLE IF NOT EXISTS bill_payments (
  id TEXT PRIMARY KEY,
  bill_id TEXT NOT NULL REFERENCES bills(id),
  month TEXT NOT NULL,                  -- YYYY-MM
  paid INTEGER NOT NULL DEFAULT 0,
  paid_amount REAL,
  paid_date TEXT,                       -- YYYY-MM-DD
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(bill_id, month)
);

CREATE TABLE IF NOT EXISTS month_closings (
  id TEXT PRIMARY KEY,
  month TEXT UNIQUE NOT NULL,           -- YYYY-MM
  closed_at TEXT NOT NULL,
  note TEXT
);
