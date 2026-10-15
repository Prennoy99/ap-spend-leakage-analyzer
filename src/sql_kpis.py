"""Runs the SQL versions of the KPIs in sql/ with DuckDB, straight on the
parquet files in data/processed/.

The pandas functions in kpis.py stay the source of truth for the app. The SQL
layer shows the same logic as warehouse queries that can be moved to the
client's own platform, and tests/test_sql_parity.py checks both give the
same answer. Thresholds are passed in from the Python constants, never
retyped in SQL, so the two versions can't drift apart.
"""

from pathlib import Path

import duckdb
import pandas as pd

from src.anomalies import BUDGET_OVERRUN_THRESHOLD, DUPLICATE_DATE_WINDOW_DAYS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = PROJECT_ROOT / "sql"
VIEWS_FILE = SQL_DIR / "00_views.sql"

# Default value for each $parameter a query uses.
DEFAULT_PARAMS = {
    "spend_by_vendor": {"top_n": 10},
    "duplicate_pairs": {"window_days": DUPLICATE_DATE_WINDOW_DAYS},
    "repeat_overruns": {"threshold": BUDGET_OVERRUN_THRESHOLD},
}


def connect() -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB connection with the invoices, vendors, budgets and
    invoice_events views defined over the parquet files.
    """
    con = duckdb.connect()
    # The views use paths relative to the project root, so the same file also
    # runs from the DuckDB command line there.
    con.execute(f"SET file_search_path = '{PROJECT_ROOT}'")
    con.execute(VIEWS_FILE.read_text())
    return con


def query_names() -> list[str]:
    return sorted(p.stem for p in SQL_DIR.glob("*.sql") if p != VIEWS_FILE)


def run_query(name: str, con: duckdb.DuckDBPyConnection | None = None, **params) -> pd.DataFrame:
    """Run sql/<name>.sql and return the result. Keyword arguments override
    the default $parameters, e.g. run_query("spend_by_vendor", top_n=5).
    """
    sql = (SQL_DIR / f"{name}.sql").read_text()
    params = {**DEFAULT_PARAMS.get(name, {}), **params}
    if con is None:
        con = connect()
    return con.execute(sql, params or None).df()


if __name__ == "__main__":
    con = connect()
    for name in query_names():
        result = run_query(name, con)
        print(f"-- {name} ({len(result)} rows)")
        print(result.head(5).to_string(index=False))
        print()
