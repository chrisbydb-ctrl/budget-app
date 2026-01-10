import os
from datetime import date
from typing import Optional

import pandas as pd
import streamlit as st

import services

st.set_page_config(page_title="Budget App", layout="wide")
services.init_db()

st.title("Budget + Expense + Bills + Debt Progress")


# ---------------- Helpers ----------------
def month_now() -> str:
    return date.today().strftime("%Y-%m")


def owners_maps():
    owners = services.get_owners()
    label_to_id = {o["display_name"]: o["id"] for o in owners}
    return owners, label_to_id


def df_from_rows(rows) -> pd.DataFrame:
    """
    Make a DataFrame with real column names from sqlite3.Row (or dict rows).
    Avoids RangeIndex columns (0..n) which cause KeyError like 'paid'/'owner'.
    """
    if rows is None:
        return pd.DataFrame()
    if isinstance(rows, list) and len(rows) == 0:
        return pd.DataFrame()
    try:
        return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame(rows)


def month_selector(label: str, key: str, default: Optional[str] = None) -> str:
    """
    Dropdown that auto-fills months found in data, always includes current month.
    Allows manual entry via 'Custom…'.
    Compatible with Python < 3.10 (uses Optional).
    """
    current = month_now()
    known = services.get_known_months(limit=48)

    if current not in known:
        known = [current] + known

    default_month = (default or current).strip()
    if default_month not in known:
        known = [default_month] + known

    options = known + ["Custom…"]

    state_key = f"{key}_selected"
    if state_key not in st.session_state:
        st.session_state[state_key] = default_month

    sel = st.selectbox(label, options, index=options.index(st.session_state[state_key]), key=f"{key}_select")

    if sel == "Custom…":
        custom = st.text_input("Custom month (YYYY-MM)", value=st.session_state[state_key], key=f"{key}_custom").strip()
        if len(custom) == 7 and custom[4] == "-":
            st.session_state[state_key] = custom
            return custom
        st.warning("Enter month as YYYY-MM (example: 2026-01).")
        return st.session_state[state_key]
    else:
        st.session_state[state_key] = sel
        return sel


def arm_two_step_if_closed(month: str, action_key: str):
    pending_key = f"pending_{action_key}_{month}"
    if services.is_month_closed(month):
        st.session_state[pending_key] = True


def confirm_bar_if_pending(month: str, action_key: str, warning: str) -> bool:
    """
    If month is closed and a pending flag is set, show Confirm/Cancel.
    Returns True only when Confirm is clicked.
    """
    month = (month or "").strip()
    pending_key = f"pending_{action_key}_{month}"

    if not services.is_month_closed(month):
        st.session_state.pop(pending_key, None)
        return False

    if not st.session_state.get(pending_key, False):
        return False

    st.warning(f"⚠️ {warning} ({month} is CLOSED)")
    c1, c2 = st.columns(2)
    if c1.button("Confirm Save", key=f"confirm_{action_key}_{month}", type="primary"):
        st.session_state[pending_key] = False
        return True
    if c2.button("Cancel", key=f"cancel_{action_key}_{month}"):
        st.session_state[pending_key] = False
        st.rerun()
    return False


def download_db_button():
    if os.path.exists("budget.db"):
        with open("budget.db", "rb") as f:
            st.download_button(
                label="Download backup (budget.db)",
                data=f.read(),
                file_name="budget.db",
                mime="application/octet-stream",
                use_container_width=True,
            )
    else:
        st.info("Database file not found yet. Add some data first.")


def safe_owner_totals_from_pva(pva: pd.DataFrame):
    needed = {"owner", "planned", "actual", "variance"}
    if pva is None or pva.empty or not needed.issubset(set(pva.columns)):
        return None
    return pva.groupby("owner")[["planned", "actual", "variance"]].sum().reset_index()


# ---------------- Tabs ----------------
tabs = st.tabs([
    "Setup Wizard",
    "Dashboard",
    "Add Expense",
    "Transactions",
    "Budgets (Planned vs Actual)",
    "Bills Due",
    "Accounts + Snapshots",
    "Debt Progress",
    "Monthly Closeout",
    "Data Tools (Backup + CSV)",
    "Settings",
])

# ---------------- Setup Wizard ----------------
with tabs[0]:
    st.subheader("Setup Wizard")
    first_run = services.is_first_run()

    if first_run:
        st.info("Welcome! Do these once, and you’ll be ready to budget quickly.")
    else:
        st.caption("You can use this wizard any time (names, starter categories, etc.).")

    owners = services.get_owners()

    st.markdown("### 1) Name your buckets")
    for o in owners:
        new = st.text_input(o["system_key"], value=o["display_name"], key=f"wiz_name_{o['id']}")
        if new != o["display_name"]:
            try:
                services.rename_owner(o["id"], new)
                st.success("Updated.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.markdown("### 2) Add starter categories")
    st.caption("One per line. You can rename/deactivate later.")
    starter = st.text_area(
        "Categories",
        value="Housing\nUtilities\nGroceries\nTransportation\nHealth\nDining\nEntertainment\nSubscriptions\nSavings\nMisc",
        height=160,
        key="wiz_cats",
    )
    if st.button("Add these categories", type="primary"):
        added = 0
        for line in starter.splitlines():
            name = line.strip()
            if name:
                try:
                    services.add_category(name)
                    added += 1
                except Exception:
                    pass
        st.success(f"Done. Attempted to add {added} categories (duplicates ignored).")
        st.rerun()

    st.divider()
    st.markdown("### 3) Optional: add a couple starter bills")
    st.caption("Add just a few now; add the rest later in Settings.")
    owners, owner_label_to_id = owners_maps()
    b1, b2, b3, b4 = st.columns(4)
    bo = b1.selectbox("Owner", list(owner_label_to_id.keys()), key="wiz_bill_owner")
    bn = b2.text_input("Bill name", key="wiz_bill_name")
    bd = b3.number_input("Due day", min_value=1, max_value=31, step=1, value=1, key="wiz_bill_due")
    ba = b4.number_input("Default amount", min_value=0.0, step=1.0, value=0.0, key="wiz_bill_amt")
    if st.button("Add starter bill"):
        try:
            services.add_bill(owner_label_to_id[bo], bn, int(bd), float(ba))
            st.success("Bill added.")
            st.rerun()
        except Exception as e:
            st.error(str(e))

    st.divider()
    st.markdown("### 4) Optional: add a starter account")
    a1, a2, a3 = st.columns(3)
    ao = a1.selectbox("Owner", list(owner_label_to_id.keys()), key="wiz_acc_owner")
    an = a2.text_input("Account name", key="wiz_acc_name")
    at = a3.selectbox("Type", ["CREDIT_CARD", "LOAN"], key="wiz_acc_type")
    a4, a5, a6 = st.columns(3)
    apr = a4.number_input("APR (%)", min_value=0.0, step=0.1, value=0.0, key="wiz_acc_apr")
    limit_val = a5.number_input("Credit limit (cards)", min_value=0.0, step=10.0, value=0.0, key="wiz_acc_limit")
    start_bal = a6.number_input("Start balance", min_value=0.0, step=10.0, value=0.0, key="wiz_acc_start")
    if st.button("Add starter account"):
        try:
            services.add_account(
                owner_label_to_id[ao],
                an,
                at,
                apr if apr > 0 else None,
                limit_val if at == "CREDIT_CARD" and limit_val > 0 else None,
                start_bal if start_bal > 0 else None,
            )
            st.success("Account added.")
            st.rerun()
        except Exception as e:
            st.error(str(e))

# ---------------- Dashboard ----------------
with tabs[1]:
    st.subheader("Dashboard")
    m = month_selector("Month", key="dash_month", default=month_now()).strip()

    if services.is_month_closed(m):
        st.info(f"🔒 {m} is CLOSED. You can still edit (with confirmation).")

    bills = df_from_rows(services.bills_due_view(m))
    if not bills.empty and "paid" in bills.columns:
        unpaid = bills[bills["paid"] == 0]
        planned_total = float(bills.get("planned", pd.Series([0])).fillna(0).sum())
        unpaid_planned = float(unpaid.get("planned", pd.Series([0])).fillna(0).sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("Bills (planned)", f"${planned_total:,.2f}")
        c2.metric("Bills unpaid (count)", f"{len(unpaid)}")
        c3.metric("Bills unpaid (planned $)", f"${unpaid_planned:,.2f}")
    else:
        st.info("Add bills to see bill metrics.")

    # Planned vs Actual totals
    try:
        pva = df_from_rows(services.planned_vs_actual(m))
    except Exception:
        pva = pd.DataFrame()

    if not pva.empty:
        st.markdown("### Planned vs Actual")
        st.dataframe(pva, use_container_width=True)

        totals = safe_owner_totals_from_pva(pva)
        if totals is not None:
            st.markdown("### Owner totals")
            st.dataframe(totals, use_container_width=True)

            grand = totals[["planned", "actual", "variance"]].sum()
            c4, c5, c6 = st.columns(3)
            c4.metric("Planned (total)", f"${grand['planned']:,.2f}")
            c5.metric("Actual (total)", f"${grand['actual']:,.2f}")
            c6.metric("Variance (total)", f"${grand['variance']:,.2f}")
        else:
            st.info("No totals yet. Add categories and transactions/budgets.")
    else:
        st.info("Add categories + budgets/transactions to see planned vs actual totals.")

    prog = df_from_rows(services.latest_snapshot_by_account(m))
    if not prog.empty and "curr_balance" in prog.columns and "type" in prog.columns:
        st.markdown("### Debt totals (from snapshots)")
        totals = prog.dropna(subset=["curr_balance"]).groupby("type")["curr_balance"].sum().reset_index()
        totals = totals.rename(columns={"curr_balance": "total_balance"})
        st.dataframe(totals, use_container_width=True)

        st.markdown("### Accounts missing a snapshot this month")
        if "owner" in prog.columns and "account" in prog.columns:
            missing = prog[prog["curr_balance"].isna()][["owner", "account", "type"]]
            st.dataframe(missing, use_container_width=True)
    else:
        st.info("Add accounts + monthly snapshots to see debt overview.")

# ---------------- Add Expense ----------------
with tabs[2]:
    st.subheader("Add Expense")

    owners, owner_label_to_id = owners_maps()
    cats_active = services.get_categories(active_only=True)
    cat_name_to_id = {c["name"]: c["id"] for c in cats_active}

    c1, c2, c3, c4 = st.columns(4)
    d = c1.date_input("Date", value=date.today())
    owner_label = c2.selectbox("Owner", list(owner_label_to_id.keys()))
    desc = st.text_input("Description (optional)")

    if not cats_active:
        st.warning("No categories yet. Add them in Setup Wizard or Settings.")
    else:
        cat_name = c3.selectbox("Category", list(cat_name_to_id.keys()))
        amt = c4.number_input("Amount", min_value=0.01, step=1.0)

        txn_month = d.isoformat()[:7]

        if confirm_bar_if_pending(txn_month, "add_expense", "You’re about to add an expense to a closed month"):
            try:
                services.add_transaction(
                    txn_date=d.isoformat(),
                    owner_id=owner_label_to_id[owner_label],
                    category_id=cat_name_to_id[cat_name],
                    amount=float(amt),
                    desc=desc,
                )
                st.success("Saved.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

        if st.button("Save expense", type="primary"):
            if services.is_month_closed(txn_month):
                arm_two_step_if_closed(txn_month, "add_expense")
                st.rerun()
            try:
                services.add_transaction(
                    txn_date=d.isoformat(),
                    owner_id=owner_label_to_id[owner_label],
                    category_id=cat_name_to_id[cat_name],
                    amount=float(amt),
                    desc=desc,
                )
                st.success("Saved.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

# ---------------- Transactions ----------------
with tabs[3]:
    st.subheader("Transactions")
    m = month_selector("Filter month", key="txn_month", default=month_now())
    show_all = st.checkbox("Show all months (ignore filter)", value=False)

    rows = services.get_transactions(None if show_all else m)
    df = df_from_rows(rows)

    if not df.empty and "id" in df.columns:
        st.dataframe(df.drop(columns=["id"]), use_container_width=True)
        st.caption("Soft delete removes it from reports but keeps history.")
        del_id = st.selectbox("Select a transaction to delete", df["id"].tolist())
        if st.button("Delete selected transaction"):
            services.soft_delete_transaction(del_id)
            st.success("Deleted.")
            st.rerun()
    else:
        st.dataframe(df, use_container_width=True)

# ---------------- Budgets ----------------
with tabs[4]:
    st.subheader("Budgets (Planned vs Actual)")

    owners, owner_label_to_id = owners_maps()
    cats_active = services.get_categories(active_only=True)
    m = month_selector("Month", key="bud_month", default=month_now()).strip()

    if services.is_month_closed(m):
        st.info(f"🔒 {m} is CLOSED. Budget edits require confirmation.")

    st.markdown("### Quick set planned amount")
    if not cats_active:
        st.warning("Add categories first (Setup Wizard or Settings).")
    else:
        b1, b2, b3 = st.columns(3)
        o = b1.selectbox("Owner", list(owner_label_to_id.keys()), key="bud_owner")
        cat = b2.selectbox("Category", [c["name"] for c in cats_active], key="bud_cat")
        planned = b3.number_input("Planned amount", min_value=0.0, step=10.0, key="bud_amt")

        def do_budget_write():
            cat_id = next(c["id"] for c in cats_active if c["name"] == cat)
            services.upsert_budget(m, owner_label_to_id[o], cat_id, float(planned))

        if confirm_bar_if_pending(m, "save_budget", "You’re about to change a budget in a closed month"):
            try:
                do_budget_write()
                st.success("Saved planned amount.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

        if st.button("Save planned amount", key="bud_save"):
            if services.is_month_closed(m):
                arm_two_step_if_closed(m, "save_budget")
                st.rerun()
            try:
                do_budget_write()
                st.success("Saved planned amount.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.markdown("### Planned vs Actual grid")
    try:
        pva = df_from_rows(services.planned_vs_actual(m))
        if pva.empty:
            st.info("No rows yet. Add categories and budgets/transactions.")
        else:
            st.dataframe(pva, use_container_width=True)

            totals = safe_owner_totals_from_pva(pva)
            if totals is not None:
                st.markdown("### Owner totals")
                st.dataframe(totals, use_container_width=True)
    except Exception as e:
        st.error(str(e))

# ---------------- Bills Due ----------------
with tabs[5]:
    st.subheader("Bills Due")
    m = month_selector("Month", key="bills_month", default=month_now()).strip()

    if services.is_month_closed(m):
        st.info(f"🔒 {m} is CLOSED. Payment edits require confirmation.")

    rows = services.bills_due_view(m)
    df = df_from_rows(rows)

    if df.empty:
        st.info("No bills yet. Add bills in Setup Wizard or Settings.")
    else:
        show_df = df.drop(columns=["bill_id"]) if "bill_id" in df.columns else df
        st.dataframe(show_df, use_container_width=True)

        planned_total = float(df["planned"].fillna(0).sum()) if "planned" in df.columns else 0.0
        paid_total = 0.0
        if {"paid", "paid_amount"}.issubset(set(df.columns)):
            paid_total = float(df.apply(lambda r: (r["paid_amount"] or 0) if int(r["paid"]) == 1 else 0, axis=1).sum())

        colA, colB = st.columns(2)
        colA.metric("Planned total", f"${planned_total:,.2f}")
        colB.metric("Paid total", f"${paid_total:,.2f}")

        st.markdown("### Mark bill paid / unpaid")
        if "bill" in df.columns and "bill_id" in df.columns:
            pick = st.selectbox("Select bill", df["bill"].tolist(), key="bill_pick")
            picked = df[df["bill"] == pick].iloc[0]

            paid = st.checkbox("Paid?", value=(int(picked.get("paid", 0)) == 1), key="bill_paid")
            paid_amount_default = float(picked.get("paid_amount") or picked.get("planned") or 0)
            paid_amount = st.number_input("Paid amount", min_value=0.0, step=1.0, value=paid_amount_default, key="bill_paid_amt")
            paid_date = st.date_input("Paid date", value=date.today(), key="bill_paid_date")
            note = st.text_input("Note", value=str(picked.get("note") or ""), key="bill_note")

            def do_bill_write():
                services.set_bill_paid(
                    month=m,
                    bill_id=str(picked["bill_id"]),
                    paid=bool(paid),
                    paid_amount=float(paid_amount) if paid else None,
                    paid_date=paid_date.isoformat() if paid else None,
                    note=note,
                )

            if confirm_bar_if_pending(m, "save_bill_payment", "You’re about to update bill payment status in a closed month"):
                do_bill_write()
                st.success("Updated.")
                st.rerun()

            if st.button("Save payment status", key="bill_save"):
                if services.is_month_closed(m):
                    arm_two_step_if_closed(m, "save_bill_payment")
                    st.rerun()
                do_bill_write()
                st.success("Updated.")
                st.rerun()

# ---------------- Accounts + Snapshots ----------------
with tabs[6]:
    st.subheader("Accounts + Monthly Snapshots")

    owners, owner_label_to_id = owners_maps()

    st.markdown("### Add account")
    a1, a2, a3 = st.columns(3)
    o = a1.selectbox("Owner", list(owner_label_to_id.keys()), key="acc_owner")
    name = a2.text_input("Account name", key="acc_name")
    acc_type = a3.selectbox("Type", ["CREDIT_CARD", "LOAN"], key="acc_type")

    a4, a5, a6 = st.columns(3)
    apr = a4.number_input("APR (%)", min_value=0.0, step=0.1, key="acc_apr")
    limit_val = a5.number_input("Credit limit (cards only)", min_value=0.0, step=10.0, key="acc_limit")
    start_bal = a6.number_input("Start balance (optional)", min_value=0.0, step=10.0, key="acc_start")

    if st.button("Add account", key="acc_add"):
        try:
            services.add_account(
                owner_label_to_id[o],
                name,
                acc_type,
                apr if apr > 0 else None,
                limit_val if acc_type == "CREDIT_CARD" and limit_val > 0 else None,
                start_bal if start_bal > 0 else None,
            )
            st.success("Account added.")
            st.rerun()
        except Exception as e:
            st.error(str(e))

    st.markdown("### Save monthly snapshot")
    m = month_selector("Snapshot month", key="snap_month", default=month_now()).strip()

    if services.is_month_closed(m):
        st.info(f"🔒 {m} is CLOSED. Snapshot edits require confirmation.")

    accounts = services.get_accounts(active_only=True)
    accounts_df = df_from_rows(accounts)

    if accounts_df.empty:
        st.info("Add an account first (Setup Wizard or above).")
    else:
        labels = [f"{r['owner']} • {r['name']} ({r['type']})" for _, r in accounts_df.iterrows()]
        pick = st.selectbox("Pick account", labels, key="snap_pick")
        picked = accounts_df.iloc[labels.index(pick)]

        s1, s2 = st.columns(2)
        bal = s1.number_input("Balance", min_value=0.0, step=10.0, key="snap_bal")
        pay = s2.number_input("Payment this month", min_value=0.0, step=10.0, key="snap_pay")

        def do_snap_write():
            services.upsert_snapshot(str(picked["id"]), m, float(bal), float(pay))

        if confirm_bar_if_pending(m, "save_snapshot", "You’re about to update an account snapshot in a closed month"):
            do_snap_write()
            st.success("Saved.")
            st.rerun()

        if st.button("Save snapshot", key="snap_save"):
            if services.is_month_closed(m):
                arm_two_step_if_closed(m, "save_snapshot")
                st.rerun()
            try:
                do_snap_write()
                st.success("Saved.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.markdown("### Snapshot history")
    snaps = df_from_rows(services.get_snapshots())
    st.dataframe(snaps, use_container_width=True)

# ---------------- Debt Progress ----------------
with tabs[7]:
    st.subheader("Debt Progress")
    m = month_selector("Month", key="prog_month", default=month_now()).strip()

    rows = services.latest_snapshot_by_account(m)
    df = df_from_rows(rows)

    if df.empty:
        st.info("Add accounts + monthly snapshots to see progress.")
    else:
        def pct_used(r):
            lim = r.get("credit_limit")
            cb = r.get("curr_balance")
            if lim is not None and pd.notna(lim) and float(lim) > 0 and cb is not None and pd.notna(cb):
                return round(100.0 * float(cb) / float(lim), 1)
            return None

        def payoff_pct(r):
            sb = r.get("start_balance")
            cb = r.get("curr_balance")
            if sb is not None and pd.notna(sb) and float(sb) > 0 and cb is not None and pd.notna(cb):
                return round(100.0 * (float(sb) - float(cb)) / float(sb), 1)
            return None

        def delta_balance(r):
            cb = r.get("curr_balance")
            pb = r.get("prev_balance")
            if cb is None or pb is None or pd.isna(cb) or pd.isna(pb):
                return None
            return round(float(cb) - float(pb), 2)

        df["utilization_%"] = df.apply(pct_used, axis=1)
        df["payoff_%"] = df.apply(payoff_pct, axis=1)
        df["balance_delta"] = df.apply(delta_balance, axis=1)

        show_cols = [
            "owner", "account", "type", "apr",
            "curr_balance", "curr_payment", "prev_balance", "balance_delta",
            "credit_limit", "utilization_%", "start_balance", "payoff_%"
        ]
        existing_cols = [c for c in show_cols if c in df.columns]
        st.dataframe(df[existing_cols], use_container_width=True)

# ---------------- Monthly Closeout ----------------
with tabs[8]:
    st.subheader("Monthly Closeout")
    m = month_selector("Month to close", key="close_month", default=month_now()).strip()

    if services.is_month_closed(m):
        st.success(f"{m} is already CLOSED.")
    else:
        st.warning(f"{m} is OPEN.")
        note = st.text_input("Closeout note (optional)", key="close_note")
        if st.button("Close month", type="primary", key="close_btn"):
            try:
                services.close_month(m, note=note)
                st.success(f"Closed {m}.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.markdown("### Closeout history")
    st.dataframe(df_from_rows(services.get_month_closings()), use_container_width=True)

# ---------------- Data Tools (Backup + CSV) ----------------
with tabs[9]:
    st.subheader("Data Tools")
    st.markdown("### Backup")
    download_db_button()

    st.divider()
    st.markdown("### Export transactions to CSV")
    export_month = month_selector("Export month", key="export_month", default=month_now())
    export_all = st.checkbox("Export ALL transactions (ignore month)", value=False, key="export_all")

    export_rows = services.export_transactions_rows(None if export_all else export_month)
    export_df = pd.DataFrame(export_rows)
    st.dataframe(export_df, use_container_width=True)

    if not export_df.empty:
        csv_bytes = export_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download CSV",
            data=csv_bytes,
            file_name=("transactions_all.csv" if export_all else f"transactions_{export_month}.csv"),
            mime="text/csv",
            use_container_width=True,
        )

    st.divider()
    st.markdown("### Import transactions from CSV")
    st.caption("CSV columns supported: txn_date/date, owner, category, amount, description (optional).")
    uploaded = st.file_uploader("Upload CSV", type=["csv"], key="csv_upload")

    if uploaded is not None:
        try:
            df_in = pd.read_csv(uploaded)
        except Exception as e:
            st.error(f"Could not read CSV: {e}")
            df_in = None

        if df_in is not None:
            df_norm = df_in.copy()
            df_norm.columns = [c.strip().lower() for c in df_norm.columns]

            if "txn_date" not in df_norm.columns and "date" in df_norm.columns:
                df_norm["txn_date"] = df_norm["date"]

            required = ["txn_date", "owner", "category", "amount"]
            missing_cols = [c for c in required if c not in df_norm.columns]
            if missing_cols:
                st.error(f"Missing required columns: {missing_cols}")
            else:
                df_norm["txn_date"] = df_norm["txn_date"].astype(str).str.strip()
                df_norm["owner"] = df_norm["owner"].astype(str).str.strip()
                df_norm["category"] = df_norm["category"].astype(str).str.strip()
                df_norm["description"] = df_norm.get("description", "").astype(str).fillna("").str.strip()

                def to_amount(x):
                    try:
                        return float(str(x).replace("$", "").replace(",", "").strip())
                    except Exception:
                        return None

                df_norm["amount"] = df_norm["amount"].apply(to_amount)

                bad_date = df_norm[~df_norm["txn_date"].str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)]
                bad_amt = df_norm[df_norm["amount"].isna() | (df_norm["amount"] <= 0)]

                if not bad_date.empty:
                    st.error("Some txn_date values are not YYYY-MM-DD. Fix these rows and re-upload.")
                    st.dataframe(bad_date, use_container_width=True)

                if not bad_amt.empty:
                    st.error("Some amount values are missing or <= 0. Fix these rows and re-upload.")
                    st.dataframe(bad_amt, use_container_width=True)

                if bad_date.empty and bad_amt.empty:
                    unresolved_owners = []
                    prepared_rows = []
                    months_touched = set()

                    for _, r in df_norm.iterrows():
                        owner_id = services.owner_id_from_label_or_key(r["owner"])
                        if not owner_id:
                            unresolved_owners.append(r["owner"])
                            continue

                        cat_id = services.get_or_create_category_id(r["category"])
                        prepared_rows.append({
                            "txn_date": r["txn_date"],
                            "owner_id": owner_id,
                            "category_id": cat_id,
                            "amount": float(r["amount"]),
                            "description": r["description"] or "",
                        })
                        months_touched.add(r["txn_date"][:7])

                    if unresolved_owners:
                        st.error("These owners could not be matched to your 3 buckets (case-insensitive):")
                        st.write(sorted(set(unresolved_owners)))
                        st.info("Fix CSV owners to match your bucket names, or use shared/person_1/person_2.")
                    else:
                        st.markdown("#### Preview import")
                        st.dataframe(pd.DataFrame(prepared_rows).drop(columns=["owner_id", "category_id"]), use_container_width=True)

                        closed_months = sorted([mm for mm in months_touched if services.is_month_closed(mm)])
                        if closed_months:
                            st.warning(f"This import touches CLOSED month(s): {closed_months}")

                        action_key = "csv_import_" + "_".join(sorted(months_touched)) if months_touched else "csv_import"

                        if closed_months:
                            if st.button("Import CSV (requires confirmation)", type="primary", key="csv_import_btn"):
                                st.session_state[f"pending_{action_key}"] = True
                                st.rerun()

                            if st.session_state.get(f"pending_{action_key}", False):
                                st.warning("⚠️ You are about to import into one or more CLOSED months.")
                                c1, c2 = st.columns(2)
                                if c1.button("Confirm Import", type="primary", key="csv_confirm"):
                                    services.bulk_add_transactions(prepared_rows)
                                    st.session_state[f"pending_{action_key}"] = False
                                    st.success(f"Imported {len(prepared_rows)} transactions.")
                                    st.rerun()
                                if c2.button("Cancel", key="csv_cancel"):
                                    st.session_state[f"pending_{action_key}"] = False
                                    st.rerun()
                        else:
                            if st.button("Import CSV", type="primary", key="csv_import_btn2"):
                                services.bulk_add_transactions(prepared_rows)
                                st.success(f"Imported {len(prepared_rows)} transactions.")
                                st.rerun()

# ---------------- Settings ----------------
with tabs[10]:
    st.subheader("Settings")

    st.markdown("### Customize names (Shared / Person 1 / Person 2)")
    owners = services.get_owners()
    for o in owners:
        new = st.text_input(o["system_key"], value=o["display_name"], key=f"name_{o['id']}")
        if new != o["display_name"]:
            try:
                services.rename_owner(o["id"], new)
                st.success("Updated name.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.markdown("### Categories")
    new_cat = st.text_input("Add category", key="set_new_cat")
    if st.button("Add category", key="set_add_cat"):
        try:
            services.add_category(new_cat)
            st.success("Added.")
            st.rerun()
        except Exception as e:
            st.error(str(e))

    all_cats = services.get_categories(active_only=False)
    cdf = df_from_rows(all_cats)
    st.dataframe(cdf, use_container_width=True)

    if all_cats:
        st.markdown("#### Rename / activate-deactivate category")
        pick = st.selectbox("Pick category", [c["name"] for c in all_cats], key="set_pick_cat")
        picked = next(c for c in all_cats if c["name"] == pick)

        new_name = st.text_input("New name", value=picked["name"], key="set_cat_new_name")
        colA, colB = st.columns(2)

        if colA.button("Rename category", key="set_cat_rename"):
            try:
                services.rename_category(picked["id"], new_name)
                st.success("Renamed.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

        toggle_to = 0 if int(picked["active"]) == 1 else 1
        if colB.button("Deactivate" if toggle_to == 0 else "Activate", key="set_cat_toggle"):
            services.set_category_active(picked["id"], active=(toggle_to == 1))
            st.success("Updated.")
            st.rerun()

    st.divider()
    st.markdown("### Bills")
    owners, owner_label_to_id = owners_maps()
    b1, b2, b3, b4 = st.columns(4)
    bo = b1.selectbox("Owner", list(owner_label_to_id.keys()), key="bill_owner")
    bn = b2.text_input("Bill name", key="bill_name")
    bd = b3.number_input("Due day", min_value=1, max_value=31, step=1, key="bill_due")
    ba = b4.number_input("Default amount (planned)", min_value=0.0, step=1.0, key="bill_amt")

    if st.button("Add bill", key="bill_add_btn"):
        try:
            services.add_bill(owner_label_to_id[bo], bn, int(bd), float(ba))
            st.success("Bill added.")
            st.rerun()
        except Exception as e:
            st.error(str(e))

    bills_all = df_from_rows(services.get_bills(active_only=False))
    st.dataframe(bills_all, use_container_width=True)


