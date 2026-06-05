import os
import re
from pathlib import Path

folder = Path(r"D:\Studium\Ökobilanz\proj\Berechnete Impacts pkm")

def classify_file(stem):
    """Convert openLCA export filename to simplified mode name."""
    s = stem.lower()

    # --- MODE ---
    if "bicycle" in s or "fahrrad" in s:
        mode = "bicycle"
    elif "tram" in s:
        mode = "tram"
    elif "articulated" in s or "gelenkbus" in s or "18m" in s:
        mode = "longbus"
    elif "bus" in s:
        mode = "bus"
    elif "car" in s or "pkw" in s or "passenger car" in s:
        mode = "auto"
    elif "metro" in s or "u-bahn" in s or "ubahn" in s:
        mode = "metro"
    elif "s-bahn" in s or "sbahn" in s or "regional train" in s:
        mode = "sbahn"
    else:
        mode = "unknown"

    # --- FUEL ---
    if "battery" in s or "electric" in s or "strom" in s or "bev" in s:
        fuel = "strom"
    elif "hydrogen" in s or "fuel cell" in s or "wasserstoff" in s:
        fuel = "wasserstoff"
    elif "diesel" in s:
        fuel = "diesel"
    elif "gasoline" in s or "petrol" in s or "benzin" in s:
        fuel = "benzin"
    elif "compressed gas" in s or "cng" in s or "gas" in s:
        fuel = "gas"
    elif "biomethane" in s or "biomethanol" in s:
        fuel = "biomethane"
    else:
        fuel = None

    # --- HYBRID ---
    hybrid = "hybrid" if "hybrid" in s else None

    # --- GREEN ELECTRICITY ---
    if "grüner" in s or "gruener" in s or "green" in s or "certified" in s:
        green = "green"
    elif "mix" in s:
        green = "conv"
    else:
        green = None

    # --- YEAR (bus/longbus only) ---
    year = None
    if mode in ("bus", "longbus"):
        if "2010" in s:
            year = "2010"
        else:
            year = "2020"

    # --- ASSEMBLE ---
    parts = [mode]
    if fuel:
        parts.append(fuel)
    if hybrid:
        parts.append(hybrid)
    if green:
        parts.append(green)
    if year:
        parts.append(year)

    return "_".join(parts)


# --- RENAME ---
if not folder.exists():
    print(f"Folder not found: {folder}")
else:
    xlsx_files = list(folder.glob("*.xlsx"))
    if not xlsx_files:
        print("No xlsx files found.")
    else:
        for f in xlsx_files:
            new_name = classify_file(f.stem) + ".xlsx"
            new_path = f.parent / new_name

            if new_path == f:
                print(f"  unchanged: {f.name}")
                continue

            if new_path.exists():
                print(f"  CONFLICT (target exists): {f.name} -> {new_name}")
                continue

            try:
                f.rename(new_path)
                print(f"  {f.name} -> {new_name}")
            except Exception as e:
                print(f"  ERROR renaming {f.name}: {e}")