"""
LCA Pipeline
============
Reads openLCA xlsx exports + district SrV data.
Outputs two tables ready for DB insertion:
  - lca_per_pkm   : static, weighted, one row per mode × impact category
  - district_base : raw SrV parameters per district (no derived values)
"""

import pandas as pd
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────────────
LCA_FOLDER    = Path(r"D:\Studium\Ökobilanz\proj\Berechnete Impacts pkm")
DISTRICT_FILE = Path(r"D:\Studium\Ökobilanz\proj\data.xlsx")
OUT_FOLDER    = Path(r"D:\Studium\Ökobilanz\proj\output")
OUT_FOLDER.mkdir(parents=True, exist_ok=True)

IMPACT_COLS = ["impact_category", "unit", "result_per_pkm"]

# ── WEIGHING DEFINITIONS ──────────────────────────────────────────────────────
# Each entry: output_mode → {source_file_stem: weight}
# Weights must sum to 1.0
WEIGHTED_MODES = {
    "bus_diesel": {
        "bus_diesel_2010":      0.21 * 0.5,
        "bus_diesel_2020":      0.21 * 0.5,
        "longbus_diesel_2010":  0.79 * 0.5,
        "longbus_diesel_2020":  0.79 * 0.5,
    },
    "bus_strom_conv": {
        "bus_strom_conv_2020":      0.21,
        "longbus_strom_conv_2020":  0.79,
    },
    "bus_strom_green": {
        "bus_strom_green_2020":      0.21,
        "longbus_strom_green_2020":  0.79,
    },
}

# Passthrough modes: file stem → output mode name
PASSTHROUGH_MODES = {
    "auto_benzin":              "auto_benzin",
    "auto_diesel":              "auto_diesel",
    "auto_benzin_hybrid_conv":  "auto_hybrid_conv",
    "auto_benzin_hybrid_green": "auto_hybrid_green",
    "auto_strom_conv":          "auto_strom_conv",
    "auto_strom_green":         "auto_strom_green",
    "bicycle":                  "bike",
    "bicycle_strom_conv":       "bike_strom_conv",
    "bicycle_strom_green":      "bike_strom_green",
    "ubahn_conv":               "ubahn_conv",
    "ubahn_green":              "ubahn_green",
    "tram_strom_conv":          "tram_conv",
    "tram_strom_green":         "tram_green",
    "sbahn_conv":               "sbahn_conv",
    "sbahn_gruen":              "sbahn_green",
}

# ── LOAD ONE LCA FILE ─────────────────────────────────────────────────────────
def load_lca_file(path: Path) -> pd.DataFrame | None:
    try:
        df = pd.read_excel(path, sheet_name="Impacts", header=0)

        # Detect if real headers are in row 0 (unnamed columns = no header)
        if str(df.columns[0]).startswith("Unnamed"):
            df.columns = df.iloc[0]  # promote row 0 to header
            df = df.iloc[1:]         # drop that row from data
            df = df.reset_index(drop=True)

        # Now find the right columns by name regardless of position
        df = df.rename(columns=lambda c: str(c).strip())
        
        # Map to standard names
        col_map = {
            "Impact category": "impact_category",
            "Reference unit":  "unit",
            "Result":          "result_per_pkm",
        }
        df = df.rename(columns=col_map)

        df = df[["impact_category", "unit", "result_per_pkm"]]
        df = df.dropna(subset=["impact_category"])
        df = df.dropna(subset=["result_per_pkm"])
        df["impact_category"] = df["impact_category"].str.strip()
        df["unit"] = df["unit"].str.strip()
        df["result_per_pkm"] = pd.to_numeric(df["result_per_pkm"], errors="coerce")
        df = df.dropna(subset=["result_per_pkm"])
        return df

    except Exception as e:
        print(f"  WARNING: could not load {path.name}: {e}")
        return None


# ── LOAD ALL RAW LCA FILES INTO DICT ─────────────────────────────────────────
def load_raw_lca(folder: Path) -> dict[str, pd.DataFrame]:
    if not folder.exists():
        raise FileNotFoundError(f"LCA folder not found: {folder}")
    xlsx_files = list(folder.glob("*.xlsx"))
    if not xlsx_files:
        raise FileNotFoundError(f"No xlsx files in {folder}")

    raw = {}
    for f in xlsx_files:
        df = load_lca_file(f)
        if df is not None:
            raw[f.stem] = df
            print(f"  loaded: {f.name} ({len(df)} impact categories)")
        else:
            print(f"  SKIPPED: {f.name}")
    return raw


# ── WEIGHTED AVERAGE ──────────────────────────────────────────────────────────
def weighted_avg(raw: dict, weights: dict, output_name: str) -> pd.DataFrame | None:
    frames = []
    for stem, w in weights.items():
        if stem not in raw:
            print(f"  WARNING: {stem}.xlsx not found, skipping for {output_name}")
            continue
        df = raw[stem].copy()
        df["result_per_pkm"] = df["result_per_pkm"] * w
        frames.append(df)

    if not frames:
        print(f"  ERROR: no source files found for {output_name}")
        return None

    combined = pd.concat(frames, ignore_index=True)
    result = (combined
              .groupby(["impact_category", "unit"], as_index=False)["result_per_pkm"]
              .sum())
    result["mode"] = output_name
    return result


# ── BUILD FINAL LCA TABLE ─────────────────────────────────────────────────────
def build_lca_table(raw: dict) -> pd.DataFrame:
    rows = []

    # Weighted modes
    print("\n── Applying weights ──")
    for output_name, weights in WEIGHTED_MODES.items():
        df = weighted_avg(raw, weights, output_name)
        if df is not None:
            rows.append(df)
            print(f"  ✓ {output_name}")

    # Passthrough modes
    print("\n── Passthrough modes ──")
    for stem, output_name in PASSTHROUGH_MODES.items():
        if stem not in raw:
            print(f"  WARNING: {stem}.xlsx not found, skipping")
            continue
        df = raw[stem].copy()
        df["mode"] = output_name
        rows.append(df)
        print(f"  ✓ {output_name} ← {stem}")

    if not rows:
        raise ValueError("No LCA data could be assembled.")

    combined = pd.concat(rows, ignore_index=True)
    combined = combined[["mode", "impact_category", "unit", "result_per_pkm"]]
    return combined.sort_values(["mode", "impact_category"]).reset_index(drop=True)


# ── LOAD DISTRICT BASE DATA ───────────────────────────────────────────────────
def load_district_base(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"District file not found: {path}")

    df = pd.read_excel(path, sheet_name="Nutzungsstatistik")

    keep = {
        "bezirk_nr":               "district_id",
        "bezirk_name":             "district_name",
        "wege_pro_tag":            "trips_per_day",
        "entfernung_km_pro_weg":   "km_per_trip",
        "homeoffice_pct":          "homeoffice_pct",
        "pkw_besetzung":           "auto_besetzung",
        "fuss_bezirk":             "split_fuss",
        "rad_bezirk":              "split_rad",
        "opnv_bezirk":             "split_opnv",
        "auto_bezirk":             "split_auto",
        "anteil_ubahn_gewichtet":  "opnv_share_ubahn",
        "anteil_sbahn_gewichtet":  "opnv_share_sbahn",
        "anteil_bus_gewichtet":    "opnv_share_bus",
        "anteil_tram_gewichtet":   "opnv_share_tram",
        "antrieb_benzin_pct":      "auto_share_benzin",
        "antrieb_diesel_pct":      "auto_share_diesel",
        "antrieb_phev_pct":        "auto_share_phev",
        "antrieb_elektro_pct":     "auto_share_elektro",
        "hh_groesse":              "household_size",
        "bevoelkerung":            "population",
        "privat_pkw_pro_hh":       "car_per_household"
    }

    available = {k: v for k, v in keep.items() if k in df.columns}
    missing   = [k for k in keep if k not in df.columns]
    if missing:
        print(f"  WARNING: missing columns: {missing}")

    df = df[list(available.keys())].rename(columns=available)
    df = df[pd.to_numeric(df["district_id"], errors="coerce").notna()]
    df["district_id"] = df["district_id"].astype(int)

    opnv_cols = ["opnv_share_ubahn", "opnv_share_sbahn",
                 "opnv_share_bus", "opnv_share_tram"]
    for col in opnv_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    corrupted = df[[c for c in opnv_cols if c in df.columns]].isnull().any(axis=1)
    if corrupted.any():
        print(f"  WARNING: {corrupted.sum()} districts have corrupted ÖPNV shares → NaN")
        print(df.loc[corrupted, ["district_id", "district_name"]].to_string(index=False))

    print(f"  loaded {len(df)} districts")
    return df


# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n── Loading raw LCA files ──")
    raw = load_raw_lca(LCA_FOLDER)
    print(f"\n  Raw files loaded: {len(raw)}")

    print("\n── Building weighted LCA table ──")
    lca = build_lca_table(raw)
    print(f"\n  Final modes: {sorted(lca['mode'].unique())}")
    print(f"  Total rows:  {len(lca)}")

    print("\n── Loading district base data ──")
    base = load_district_base(DISTRICT_FILE)

    print("\n── Saving outputs ──")
    lca_out  = OUT_FOLDER / "lca_per_pkm.csv"
    base_out = OUT_FOLDER / "district_base.csv"
    lca.to_csv(lca_out,  index=False, encoding="utf-8")
    base.to_csv(base_out, index=False, encoding="utf-8")
    print(f"  lca_per_pkm   → {lca_out}")
    print(f"  district_base → {base_out}")

    print("\n── LCA preview ──")
    print(lca.head(12).to_string(index=False))

    print("\n── District preview ──")
    print(base[["district_id", "district_name", "km_per_trip",
                "split_opnv", "split_auto",
                "opnv_share_ubahn", "opnv_share_sbahn"]].head(5).to_string(index=False))

    print("\nDone.")
