-- Views over the cleaned parquet files, so every KPI query reads like it would
-- against a warehouse table. Paths are relative to the project root: start the
-- DuckDB command line there and run .read sql/00_views.sql, or let
-- src/sql_kpis.py set file_search_path for you.

CREATE OR REPLACE VIEW invoices AS
SELECT * FROM read_parquet('data/processed/invoices_clean.parquet');

CREATE OR REPLACE VIEW vendors AS
SELECT * FROM read_parquet('data/processed/vendors_clean.parquet');

CREATE OR REPLACE VIEW budgets AS
SELECT * FROM read_parquet('data/processed/budgets.parquet');

CREATE OR REPLACE VIEW invoice_events AS
SELECT * FROM read_parquet('data/processed/invoice_events.parquet');
