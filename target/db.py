"""SQLite storage for the stand-in app (so the SQL data-validation tests are meaningful)."""

from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional

from .seed import CATEGORIES, build_seed, hash_pw

SCHEMA = """
CREATE TABLE users (
  user_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
  email TEXT NOT NULL, phone TEXT NOT NULL, account_number TEXT NOT NULL);
CREATE TABLE budgets (
  user_id TEXT NOT NULL REFERENCES users(user_id), category TEXT NOT NULL, monthly_limit REAL NOT NULL,
  PRIMARY KEY (user_id, category));
CREATE TABLE transactions (
  id INTEGER PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(user_id), date TEXT NOT NULL,
  merchant TEXT NOT NULL, category TEXT NOT NULL, amount REAL NOT NULL, description TEXT NOT NULL);
"""


def init_db(path: str) -> None:
    con = sqlite3.connect(path)
    con.executescript("DROP TABLE IF EXISTS transactions; DROP TABLE IF EXISTS budgets; DROP TABLE IF EXISTS users;")
    con.executescript(SCHEMA)
    profiles, txns = build_seed()
    for uid, p in profiles.items():
        con.execute("INSERT INTO users VALUES (?,?,?,?,?,?)",
                    (uid, p["display_name"], hash_pw(p["password"]), p["email"], p["phone"], p["account_number"]))
        for cat, lim in p["budgets"].items():
            con.execute("INSERT INTO budgets VALUES (?,?,?)", (uid, cat, lim))
    con.executemany("INSERT INTO transactions VALUES (:id,:user_id,:date,:merchant,:category,:amount,:description)", txns)
    con.commit()
    con.close()


class Store:
    def __init__(self, path: str):
        self.path = path

    def _con(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def user(self, user_id: str) -> Optional[Dict]:
        con = self._con()
        try:
            row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                return None
            u = dict(row)
            u["budgets"] = {r["category"]: r["monthly_limit"] for r in
                            con.execute("SELECT category, monthly_limit FROM budgets WHERE user_id=?", (user_id,))}
            return u
        finally:
            con.close()

    def user_ids(self) -> List[str]:
        con = self._con()
        try:
            return [r[0] for r in con.execute("SELECT user_id FROM users ORDER BY user_id")]
        finally:
            con.close()

    def transactions(self, user_id: str, month: Optional[str] = None, category: Optional[str] = None) -> List[Dict]:
        q, args = "SELECT * FROM transactions WHERE user_id=?", [user_id]
        if month:
            q += " AND substr(date,1,7)=?"
            args.append(month)
        if category:
            assert category in CATEGORIES
            q += " AND category=?"
            args.append(category)
        con = self._con()
        try:
            return [dict(r) for r in con.execute(q + " ORDER BY date, id", args)]
        finally:
            con.close()
