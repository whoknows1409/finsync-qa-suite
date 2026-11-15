"""SQL data-quality checks on the store behind the assistant.

These mirror what you would run (e.g. in Athena) to validate an AI pipeline's
input data: nulls, ranges, referential integrity, reconciliation with the API,
and data-protection controls.
"""

from __future__ import annotations

import re
import sqlite3

import pytest
import requests

from target.seed import CATEGORIES, PROFILES


@pytest.fixture(scope="module")
def db(server):
    if not getattr(server, "db_path", None):
        pytest.skip("no database path available (set FINSYNC_DB_PATH for an external target)")
    con = sqlite3.connect(server.db_path)
    con.row_factory = sqlite3.Row
    yield con
    con.close()


def scalar(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def test_no_null_or_blank_required_fields(db):
    bad = scalar(db, "SELECT COUNT(*) FROM transactions WHERE merchant IS NULL OR TRIM(merchant)='' "
                     "OR category IS NULL OR date IS NULL OR amount IS NULL")
    assert bad == 0


def test_amounts_are_positive(db):
    assert scalar(db, "SELECT COUNT(*) FROM transactions WHERE amount <= 0") == 0


def test_categories_are_known(db):
    cats = {r[0] for r in db.execute("SELECT DISTINCT category FROM transactions")}
    assert cats <= set(CATEGORIES), f"unknown categories: {cats - set(CATEGORIES)}"


def test_dates_are_valid_iso_and_in_range(db):
    dates = [r[0] for r in db.execute("SELECT date FROM transactions")]
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) for d in dates)
    assert min(dates) >= "2026-08-01" and max(dates) <= "2026-10-31"


def test_referential_integrity(db):
    orphans = scalar(db, "SELECT COUNT(*) FROM transactions t LEFT JOIN users u USING(user_id) WHERE u.user_id IS NULL")
    assert orphans == 0


def test_every_user_has_a_budget_for_every_category(db):
    for (uid,) in db.execute("SELECT user_id FROM users").fetchall():
        n = scalar(db, "SELECT COUNT(DISTINCT category) FROM budgets WHERE user_id=?", uid)
        assert n == len(CATEGORIES), f"{uid} has budgets for {n} categories"


def test_fixed_recurring_charges_are_consistent(db):
    """A recurring merchant must charge the same amount every month; drift hints at bad ingestion."""
    rows = db.execute("""SELECT user_id, merchant, COUNT(DISTINCT amount) AS amounts, COUNT(DISTINCT substr(date,1,7)) AS months
                         FROM transactions WHERE merchant IN ('StreamFlix','FitLife Gym','CloudBox','Sunrise Residency')
                         GROUP BY user_id, merchant""").fetchall()
    assert rows and all(r["amounts"] == 1 and r["months"] == 3 for r in rows)


@pytest.mark.parametrize("user", ["alice", "bob"])
def test_db_totals_reconcile_with_api(db, client, base_url, user):
    api = requests.get(f"{base_url}/users/{user}/transactions", headers=client.headers(user), timeout=10).json()
    assert api["count"] == scalar(db, "SELECT COUNT(*) FROM transactions WHERE user_id=?", user)
    assert api["total"] == pytest.approx(scalar(db, "SELECT SUM(amount) FROM transactions WHERE user_id=?", user), abs=0.01)


def test_passwords_are_not_stored_in_plaintext(db):
    stored = {r["user_id"]: r["password_hash"] for r in db.execute("SELECT user_id, password_hash FROM users")}
    for uid, profile in PROFILES.items():
        assert stored[uid] != profile["password"]
        assert re.fullmatch(r"[0-9a-f]{64}", stored[uid])


def test_prompt_injection_payload_is_stored_as_inert_data(db):
    """The payload exists in the data on purpose; the assistant tests prove it is never obeyed."""
    n = scalar(db, "SELECT COUNT(*) FROM transactions WHERE description LIKE '%IGNORE ALL PREVIOUS INSTRUCTIONS%'")
    assert n == 1
