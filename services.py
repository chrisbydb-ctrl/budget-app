import sqlite3
import uuid
from datetime import datetime
from typing import Iterable, Optional

DB = "budget.db"


def now() -> str:
    return datetime.utcnow().isoformat()


def uid() -> str:
    return str(uuid.uuid4())


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON;")
    return c


def init_db():
    with conn() as c:
        with open("schema.sql", "r", encoding="utf-8") as f:
            c.executescript(f.read())

        seeds = [("shared", "Shared", 0), ("person_1", "Person 1", 1), ("person_2", "Person 2", 2)]
        for key, name, order in seeds:
            c.execute(
                """
                INSERT OR IGNORE INTO owners
                (id, system_key, display_name, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (uid(), key, name, order, now(), now()),
            )


# ---------------- Utilities ----------------
def month_from_date(iso_date: str) -> str:
    return iso_date[:7]  # "YYYY-MM-DD" -> "YYYY-MM"


def is_month_closed(month: str) -> bool:
    month = (month or "").strip()
    with conn() as c:
        row = c.execute("SELECT 1 FROM month_closings WHERE month=? LIMIT 1", (month,)).fetchone()
        return row is not None


def get_known_months(limit: int = 36):
    with conn() as c:
        rows = c.execute(
            """
            WITH months AS (
              SELECT DISTINCT substr(txn_date,1,7) AS m FROM transactions WHERE deleted_at IS NULL
              UNION
              SELECT DISTINCT month AS m FROM budgets
              UNION
              SELECT DISTINCT month AS m FROM bill_payments
              UNION
              SELECT DISTINCT month AS m FROM account_snapshots
              UNION
              SELECT DISTINCT month AS m FROM income
              UNION
              SELECT DISTINCT month AS m FROM month_closings
            )
            SELECT m FROM months
            WHERE m IS NOT NULL AND length(m)=7
            ORDER BY m DESC
            LIMIT ?
        """,
            (limit,),
        ).fetchall()
        return [r["m"] for r in rows]


def is_first_run() -> bool:
    """Heuristic: no categories, no bills, no accounts, no transactions."""
    with conn() as c:
        cat = c.execute("SELECT COUNT(*) n FROM categories").fetchone()["n"]
        bills = c.execute("SELECT COUNT(*) n FROM bills").fetchone()["n"]
        acc = c.execute("SELECT COUNT(*) n FROM accounts").fetchone()["n"]
        txn = c.execute("SELECT COUNT(*) n FROM transactions").fetchone()["n"]
        return (cat == 0 and bills == 0 and acc == 0 and txn == 0)


# ---------------- Owners ----------------
def get_owners():
    with conn() as c:
        return c.execute(
            """
            SELECT id, system_key, display_name
            FROM owners
            ORDER BY sort_order
        """
        ).fetchall()


def rename_owner(owner_id: str, new_name: str):
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("Name cannot be empty.")
    with conn() as c:
        c.execute(
            "UPDATE owners SET display_name=?, updated_at=? WHERE id=?",
            (new_name, now(), owner_id),
        )


def owner_id_from_label_or_key(label_or_key: str) -> Optional[str]:
    """Accept display_name (e.g., 'Chris') OR system_key (e.g., 'person_1')."""
    s = (label_or_key or "").strip()
    if not s:
        return None
    with conn() as c:
        row = c.execute(
            """
            SELECT id FROM owners
            WHERE lower(display_name)=lower(?) OR lower(system_key)=lower(?)
            LIMIT 1
        """,
            (s, s),
        ).fetchone()
        return row["id"] if row else None


# ---------------- Categories ----------------
def get_categories(active_only: bool = True):
    sql = "SELECT id, name, active FROM categories"
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY name"
    with conn() as c:
        return c.execute(sql).fetchall()


def add_category(name: str):
    name = (name or "").strip()
    if not name:
        raise ValueError("Category name cannot be empty.")
    with conn() as c:
        c.execute(
            """
            INSERT OR IGNORE INTO categories (id, name, active, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
        """,
            (uid(), name, now(), now()),
        )


def get_or_create_category_id(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("Category name cannot be empty.")
    with conn() as c:
        row = c.execute(
            "SELECT id FROM categories WHERE lower(name)=lower(?) LIMIT 1",
            (name,),
        ).fetchone()
        if row:
            return row["id"]
        new_id = uid()
        c.execute(
            """
            INSERT INTO categories (id, name, active, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
        """,
            (new_id, name, now(), now()),
        )
        return new_id


def set_category_active(category_id: str, active: bool):
    with conn() as c:
        c.execute(
            "UPDATE categories SET active=?, updated_at=? WHERE id=?",
            (1 if active else 0, now(), category_id),
        )


def rename_category(category_id: str, new_name: str):
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("Category name cannot be empty.")
    with conn() as c:
        c.execute(
            "UPDATE categories SET name=?, updated_at=? WHERE id=?",
            (new_name, now(), category_id),
        )


# ---------------- Bills ----------------
def add_bill(owner_id: str, name: str, due_day: Optional[int], default_amount: Optional[float]):
    name = (name or "").strip()
    if not name:
        raise ValueError("Bill name cannot be empty.")
    if due_day is not None and not (1 <= int(due_day) <= 31):
        raise ValueError("Due day must be 1..31.")
    with conn() as c:
        c.execute(
            """
            INSERT INTO bills (id, owner_id, name, due_day, default_amount, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """,
            (
                uid(),
                owner_id,
                name,
                int(due_day) if due_day else None,
                float(default_amount) if default_amount is not None else None,
                now(),
                now(),
            ),
        )


def get_bills(active_only: bool = True):
    sql = """
    SELECT b.id, b.name, b.due_day, b.default_amount, b.active,
           b.owner_id, o.display_name AS owner
    FROM bills b
    JOIN owners o ON o.id=b.owner_id
    """
    if active_only:
        sql += " WHERE b.active=1"
    sql += " ORDER BY o.display_name, b.due_day, b.name"
    with conn() as c:
        return c.execute(sql).fetchall()


def set_bill_active(bill_id: str, active: bool):
    with conn() as c:
        c.execute(
            "UPDATE bills SET active=?, updated_at=? WHERE id=?",
            (1 if active else 0, now(), bill_id),
        )


def ensure_bill_payment_rows(month: str):
    month = (month or "").strip()
    with conn() as c:
        bills = c.execute("SELECT id FROM bills WHERE active=1").fetchall()
        for b in bills:
            c.execute(
                """
                INSERT OR IGNORE INTO bill_payments
                (id, bill_id, month, paid, paid_amount, paid_date, note, created_at, updated_at)
                VALUES (?, ?, ?, 0, NULL, NULL, NULL, ?, ?)
            """,
                (uid(), b["id"], month, now(), now()),
            )


def bills_due_view(month: str):
    month = (month or "").strip()
    ensure_bill_payment_rows(month)
    with conn() as c:
        return c.execute(
            """
            SELECT o.display_name owner,
                   b.name bill,
                   b.due_day,
                   b.default_amount planned,
                   bp.paid,
                   bp.paid_amount,
                   bp.paid_date,
                   bp.note,
                   b.id bill_id
            FROM bills b
            JOIN owners o ON o.id=b.owner_id
            JOIN bill_payments bp ON bp.bill_id=b.id AND bp.month=?
            WHERE b.active=1
            ORDER BY b.due_day, o.display_name, b.name
        """,
            (month,),
        ).fetchall()


def set_bill_paid(
    month: str,
    bill_id: str,
    paid: bool,
    paid_amount: Optional[float],
    paid_date: Optional[str],
    note: Optional[str],
):
    month = (month or "").strip()
    ensure_bill_payment_rows(month)
    with conn() as c:
        c.execute(
            """
            UPDATE bill_payments
            SET paid=?, paid_amount=?, paid_date=?, note=?, updated_at=?
            WHERE bill_id=? AND month=?
        """,
            (
                1 if paid else 0,
                float(paid_amount) if paid_amount is not None else None,
                paid_date,
                (note or "").strip() if note else None,
                now(),
                bill_id,
                month,
            ),
        )


def update_bill_amount_and_recurring(bill_id: str, planned_amount: float, recurring: bool):
    """Update bill planned amount and recurring status."""
    conn = get_db()
    conn.execute(
        "UPDATE bills SET planned = ?, recurring = ? WHERE id = ?",
        (planned_amount, 1 if recurring else 0, bill_id),
    )
    conn.commit()


# ---------------- Accounts ----------------
def add_account(
    owner_id: str,
    name: str,
    acc_type: str,
    apr: Optional[float],
    credit_limit: Optional[float],
    start_balance: Optional[float],
):
    name = (name or "").strip()
    if not name:
        raise ValueError("Account name cannot be empty.")
    if acc_type not in ("CREDIT_CARD", "LOAN"):
        raise ValueError("Invalid account type.")
    with conn() as c:
        c.execute(
            """
            INSERT INTO accounts (id, owner_id, name, type, apr, credit_limit, start_balance, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
            (
                uid(),
                owner_id,
                name,
                acc_type,
                float(apr) if apr is not None else None,
                float(credit_limit) if credit_limit is not None else None,
                float(start_balance) if start_balance is not None else None,
                now(),
                now(),
            ),
        )


def get_accounts(active_only: bool = True):
    sql = """
    SELECT a.id, a.name, a.type, a.apr, a.credit_limit, a.start_balance, a.active,
           a.owner_id, o.display_name AS owner
    FROM accounts a
    JOIN owners o ON o.id=a.owner_id
    """
    if active_only:
        sql += " WHERE a.active=1"
    sql += " ORDER BY o.display_name, a.type, a.name"
    with conn() as c:
        return c.execute(sql).fetchall()


def upsert_snapshot(account_id: str, month: str, balance: float, payment: float):
    month = (month or "").strip()
    if len(month) != 7 or month[4] != "-":
        raise ValueError("Month must be YYYY-MM.")
    with conn() as c:
        c.execute(
            """
            INSERT INTO account_snapshots (id, account_id, month, balance, payment, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, month) DO UPDATE SET
              balance=excluded.balance,
              payment=excluded.payment,
              updated_at=excluded.updated_at
        """,
            (uid(), account_id, month, float(balance), float(payment), now(), now()),
        )


def get_snapshots():
    with conn() as c:
        return c.execute(
            """
            SELECT o.display_name owner, a.name account, a.type, s.month, s.balance, s.payment,
                   a.credit_limit, a.start_balance, a.id account_id
            FROM account_snapshots s
            JOIN accounts a ON a.id=s.account_id
            JOIN owners o ON o.id=a.owner_id
            WHERE a.active=1
            ORDER BY o.display_name, a.name, s.month
        """
        ).fetchall()


def latest_snapshot_by_account(month: str):
    month = (month or "").strip()
    with conn() as c:
        return c.execute(
            """
            SELECT
              o.display_name owner,
              a.name account,
              a.type,
              a.apr,
              a.credit_limit,
              a.start_balance,
              a.id account_id,
              s.balance curr_balance,
              s.payment curr_payment,
              p.balance prev_balance,
              p.payment prev_payment
            FROM accounts a
            JOIN owners o ON o.id=a.owner_id
            LEFT JOIN account_snapshots s
              ON s.account_id=a.id AND s.month=?
            LEFT JOIN account_snapshots p
              ON p.account_id=a.id AND p.month=(
                SELECT month FROM account_snapshots
                WHERE account_id=a.id AND month < ?
                ORDER BY month DESC LIMIT 1
              )
            WHERE a.active=1
            ORDER BY o.display_name, a.type, a.name
        """,
            (month, month),
        ).fetchall()


# ---------------- Transactions ----------------
def add_transaction(txn_date: str, owner_id: str, category_id: str, amount: float, desc: str = ""):
    if float(amount) <= 0:
        raise ValueError("Amount must be > 0.")
    with conn() as c:
        c.execute(
            """
            INSERT INTO transactions
            (id, txn_date, owner_id, category_id, description, amount, created_at, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
            (uid(), txn_date, owner_id, category_id, (desc or "").strip(), float(amount), now(), now()),
        )


def bulk_add_transactions(rows: Iterable[dict]):
    """
    rows: iterable of dicts with keys:
      txn_date (YYYY-MM-DD), owner_id, category_id, amount, description(optional)
    """
    with conn() as c:
        for r in rows:
            c.execute(
                """
                INSERT INTO transactions
                (id, txn_date, owner_id, category_id, description, amount, created_at, updated_at, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
                (
                    uid(),
                    r["txn_date"],
                    r["owner_id"],
                    r["category_id"],
                    (r.get("description") or "").strip(),
                    float(r["amount"]),
                    now(),
                    now(),
                ),
            )


def get_transactions(month: Optional[str] = None):
    sql = """
    SELECT t.id, t.txn_date, o.display_name owner, c.name category, t.description, t.amount
    FROM transactions t
    JOIN owners o ON o.id=t.owner_id
    JOIN categories c ON c.id=t.category_id
    WHERE t.deleted_at IS NULL
    """
    params = []
    if month:
        sql += " AND substr(t.txn_date,1,7)=?"
        params.append(month)
    sql += " ORDER BY t.txn_date DESC"
    with conn() as c:
        return c.execute(sql, params).fetchall()


def soft_delete_transaction(txn_id: str):
    with conn() as c:
        c.execute("UPDATE transactions SET deleted_at=?, updated_at=? WHERE id=?", (now(), now(), txn_id))


def export_transactions_rows(month: Optional[str] = None):
    """
    Returns a list of dicts suitable for CSV export with user-friendly owner/category names.
    """
    sql = """
    SELECT t.txn_date, o.display_name owner, c.name category, t.amount, t.description
    FROM transactions t
    JOIN owners o ON o.id=t.owner_id
    JOIN categories c ON c.id=t.category_id
    WHERE t.deleted_at IS NULL
    """
    params = []
    if month:
        sql += " AND substr(t.txn_date,1,7)=?"
        params.append(month)
    sql += " ORDER BY t.txn_date ASC"
    with conn() as c:
        rows = c.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


# ---------------- Budgets ----------------
def upsert_budget(month: str, owner_id: str, category_id: str, planned_amount: float):
    month = (month or "").strip()
    if len(month) != 7 or month[4] != "-":
        raise ValueError("Month must be YYYY-MM.")
    with conn() as c:
        c.execute(
            """
            INSERT INTO budgets (id, month, owner_id, category_id, planned_amount, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(month, owner_id, category_id) DO UPDATE SET
              planned_amount=excluded.planned_amount,
              updated_at=excluded.updated_at
        """,
            (uid(), month, owner_id, category_id, float(planned_amount), now(), now()),
        )


def planned_vs_actual(month: str):
    month = (month or "").strip()
    if len(month) != 7 or month[4] != "-":
        raise ValueError("Month must be YYYY-MM.")
    with conn() as c:
        return c.execute(
            """
            WITH act AS (
              SELECT owner_id, category_id, SUM(amount) actual
              FROM transactions
              WHERE deleted_at IS NULL AND substr(txn_date,1,7)=?
              GROUP BY owner_id, category_id
            )
            SELECT
              o.display_name owner,
              c.name category,
              COALESCE(b.planned_amount, 0) planned,
              ROUND(COALESCE(a.actual, 0), 2) actual,
              ROUND(COALESCE(b.planned_amount, 0) - COALESCE(a.actual, 0), 2) variance
            FROM owners o
            CROSS JOIN categories c
            LEFT JOIN budgets b
              ON b.month=? AND b.owner_id=o.id AND b.category_id=c.id
            LEFT JOIN act a
              ON a.owner_id=o.id AND a.category_id=c.id
            WHERE c.active=1
            ORDER BY o.sort_order, c.name
        """,
            (month, month),
        ).fetchall()


# ---------------- Month Closeout ----------------
def close_month(month: str, note: Optional[str] = None):
    month = (month or "").strip()
    if len(month) != 7 or month[4] != "-":
        raise ValueError("Month must be YYYY-MM.")
    if is_month_closed(month):
        return
    ensure_bill_payment_rows(month)
    with conn() as c:
        c.execute(
            """
            INSERT INTO month_closings (id, month, closed_at, note)
            VALUES (?, ?, ?, ?)
        """,
            (uid(), month, now(), (note or "").strip() if note else None),
        )


def get_month_closings():
    with conn() as c:
        return c.execute(
            """
            SELECT month, closed_at, note
            FROM month_closings
            ORDER BY month DESC
        """
        ).fetchall()
