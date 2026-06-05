"""
DB Setup
========
Creates lca schema and tables in PostGIS, loads CSVs.
Run once from Windows venv after lca_pipeline.py has produced the CSVs.
"""

import pandas as pd
import psycopg2
from psycopg2 import sql
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────────────
DB = {
    "host":     "localhost",
    "port":     5432,
    "dbname":   "gisdb",
    "user":     "gisuser",
    "password": "password123",
}

OUT_FOLDER = Path(r"D:\Studium\Ökobilanz\proj\output")
LCA_CSV    = OUT_FOLDER / "lca_per_pkm.csv"
BASE_CSV   = OUT_FOLDER / "district_base.csv"


# ── CONNECT ───────────────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(**DB)


# ── SCHEMA + TABLES ───────────────────────────────────────────────────────────
DDL = """
-- Schema
CREATE SCHEMA IF NOT EXISTS lca;

-- LCA per pkm (static)
DROP TABLE IF EXISTS lca.lca_per_pkm CASCADE;
CREATE TABLE lca.lca_per_pkm (
    id              SERIAL PRIMARY KEY,
    mode            TEXT NOT NULL,
    impact_category TEXT NOT NULL,
    unit            TEXT,
    result_per_pkm  DOUBLE PRECISION
);
CREATE INDEX ON lca.lca_per_pkm (mode);
CREATE INDEX ON lca.lca_per_pkm (impact_category);

-- District base (dynamic parameters)
DROP TABLE IF EXISTS lca.district_base CASCADE;
CREATE TABLE lca.district_base (
    district_id       INTEGER PRIMARY KEY,
    district_name     TEXT,
    trips_per_day     DOUBLE PRECISION,
    km_per_trip       DOUBLE PRECISION,
    homeoffice_pct    DOUBLE PRECISION,
    auto_besetzung    DOUBLE PRECISION,
    split_fuss        DOUBLE PRECISION,
    split_rad         DOUBLE PRECISION,
    split_opnv        DOUBLE PRECISION,
    split_auto        DOUBLE PRECISION,
    opnv_share_ubahn  DOUBLE PRECISION,
    opnv_share_sbahn  DOUBLE PRECISION,
    opnv_share_bus    DOUBLE PRECISION,
    opnv_share_tram   DOUBLE PRECISION,
    auto_share_benzin DOUBLE PRECISION,
    auto_share_diesel DOUBLE PRECISION,
    auto_share_phev   DOUBLE PRECISION,
    auto_share_elektro DOUBLE PRECISION,
    population         INTEGER,
    household_size     DOUBLE PRECISION,
    car_per_household  DOUBLE PRECISION
);

-- View joining district_base with geometry
DROP VIEW IF EXISTS lca.district_geo;
CREATE VIEW lca.district_geo AS
SELECT
    d.*,
    v.geom,
    v.sb_name,
    v.flaeche_qm
FROM lca.district_base d
JOIN public."vablock_stadtbezirk.geojson" v
    ON CAST(v.sb_nummer AS INTEGER) = d.district_id;
"""


def create_schema(conn):
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
    print("  ✓ Schema and tables created")


# ── LOAD CSVs ─────────────────────────────────────────────────────────────────
def load_lca(conn):
    df = pd.read_csv(LCA_CSV)
    print(f"  Loading {len(df)} rows into lca.lca_per_pkm...")

    with conn.cursor() as cur:
        cur.execute("TRUNCATE lca.lca_per_pkm RESTART IDENTITY")
        for _, row in df.iterrows():
            cur.execute(
                """
                INSERT INTO lca.lca_per_pkm (mode, impact_category, unit, result_per_pkm)
                VALUES (%s, %s, %s, %s)
                """,
                (row["mode"], row["impact_category"],
                 row.get("unit"), row["result_per_pkm"])
            )
    conn.commit()
    print("  ✓ lca_per_pkm loaded")


def load_base(conn):
    df = pd.read_csv(BASE_CSV)
    print(f"  Loading {len(df)} rows into lca.district_base...")

    # Columns that exist in both CSV and table
    table_cols = [
        "district_id", "district_name", "trips_per_day", "km_per_trip",
        "homeoffice_pct", "auto_besetzung",
        "split_fuss", "split_rad", "split_opnv", "split_auto",
        "opnv_share_ubahn", "opnv_share_sbahn", "opnv_share_bus", "opnv_share_tram",
        "auto_share_benzin", "auto_share_diesel", "auto_share_phev", "auto_share_elektro",
        "population", "household_size", "car_per_household",
    ]
    # Only use columns present in the CSV
    cols = [c for c in table_cols if c in df.columns]
    missing = [c for c in table_cols if c not in df.columns]
    if missing:
        print(f"  WARNING: missing columns in CSV, will be NULL: {missing}")

    with conn.cursor() as cur:
        cur.execute("TRUNCATE lca.district_base")
        for _, row in df.iterrows():
            values = [None if pd.isna(row.get(c)) else row.get(c) for c in cols]
            col_str = ", ".join(cols)
            placeholder = ", ".join(["%s"] * len(cols))
            cur.execute(
                f"INSERT INTO lca.district_base ({col_str}) VALUES ({placeholder})",
                values
            )
    conn.commit()
    print("  ✓ district_base loaded")


# ── VERIFY ────────────────────────────────────────────────────────────────────
def verify(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM lca.lca_per_pkm")
        lca_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM lca.district_base")
        base_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM lca.district_geo")
        geo_count = cur.fetchone()[0]

        cur.execute("SELECT DISTINCT mode FROM lca.lca_per_pkm ORDER BY mode")
        modes = [r[0] for r in cur.fetchall()]

    print(f"\n  lca_per_pkm  : {lca_count} rows")
    print(f"  district_base: {base_count} rows")
    print(f"  district_geo : {geo_count} rows (joined with geometry)")
    print(f"  Modes        : {modes}")

    if geo_count < base_count:
        print(f"  WARNING: only {geo_count}/{base_count} districts matched geometry — check sb_nummer values")


# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n── Connecting to DB ──")
    try:
        conn = get_conn()
        print("  ✓ Connected")
    except Exception as e:
        print(f"  ERROR: {e}")
        exit(1)

    try:
        print("\n── Creating schema and tables ──")
        create_schema(conn)

        print("\n── Loading LCA data ──")
        load_lca(conn)

        print("\n── Loading district base data ──")
        load_base(conn)

        print("\n── Verifying ──")
        verify(conn)

    finally:
        conn.close()
        print("\nDone.")
