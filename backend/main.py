import json
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
import calculator
from config import settings

STATIC_DIR = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    yield
    await db.close_pool()


app = FastAPI(title="München Mobilitäts-LCA", version="1.0.0", lifespan=lifespan)


# ── Request schema ─────────────────────────────────────────────────────────────

class ScenarioParams(BaseModel):
    wfh_delta: float = Field(
        default=0.0, ge=-1.0, le=1.0,
        description="Delta applied to trips_per_day; negative = fewer WFH (more trips)"
    )
    bev_delta: float = Field(
        default=0.0, ge=-1.0, le=1.0,
        description="Percentage-point delta on district BEV share"
    )
    phev_delta: float = Field(
        default=0.0, ge=-1.0, le=1.0,
        description="Percentage-point delta on district PHEV share"
    )
    ebus_share: float = Field(
        default=0.25, ge=0.0, le=1.0,
        description="Fraction of bus fleet that is electric"
    )
    green_elec: bool = Field(
        default=False,
        description="Use green-electricity LCA variants for all electric modes"
    )
    auto_besetzung_override: float | None = Field(
        default=None, ge=0.1, le=5.0,
        description="Override car occupancy; None = use district value"
    )


# ── Helper: query with optional demographic columns ────────────────────────────

_DISTRICT_SQL_FULL = """
    SELECT
        district_id, district_name, sb_name, flaeche_qm,
        trips_per_day, km_per_trip, homeoffice_pct, auto_besetzung,
        split_fuss, split_rad, split_opnv, split_auto,
        opnv_share_ubahn, opnv_share_sbahn, opnv_share_bus, opnv_share_tram,
        auto_share_benzin, auto_share_diesel, auto_share_phev, auto_share_elektro,
        population, household_size, car_per_household,
        ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geometry
    FROM lca.district_geo
    WHERE geom IS NOT NULL
    ORDER BY district_id
"""

_DISTRICT_SQL_FALLBACK = """
    SELECT
        district_id, district_name, sb_name, flaeche_qm,
        trips_per_day, km_per_trip, homeoffice_pct, auto_besetzung,
        split_fuss, split_rad, split_opnv, split_auto,
        opnv_share_ubahn, opnv_share_sbahn, opnv_share_bus, opnv_share_tram,
        auto_share_benzin, auto_share_diesel, auto_share_phev, auto_share_elektro,
        NULL::INTEGER          AS population,
        NULL::DOUBLE PRECISION AS household_size,
        NULL::DOUBLE PRECISION AS car_per_household,
        ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geometry
    FROM lca.district_geo
    WHERE geom IS NOT NULL
    ORDER BY district_id
"""


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/api/categories")
async def get_categories():
    pool = db.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT impact_category, unit
            FROM lca.lca_per_pkm
            WHERE impact_category NOT IN ('Impact category UUID', 'Impact category')
              AND result_per_pkm IS NOT NULL
            ORDER BY impact_category
            """
        )
    return [{"impact_category": r["impact_category"], "unit": r["unit"]} for r in rows]


@app.post("/api/scenario")
async def run_scenario(params: ScenarioParams):
    pool = db.get_pool()
    try:
        async with pool.acquire() as conn:
            # Load all LCA factors
            lca_rows = await conn.fetch(
                """
                SELECT mode, impact_category, result_per_pkm
                FROM lca.lca_per_pkm
                WHERE result_per_pkm IS NOT NULL
                  AND impact_category NOT IN ('Impact category UUID', 'Impact category')
                """
            )
            lca: dict = {}
            for r in lca_rows:
                lca.setdefault(r["mode"], {})[r["impact_category"]] = float(r["result_per_pkm"])

            # Load district data – try with demographic columns, fall back gracefully
            try:
                district_rows = await conn.fetch(_DISTRICT_SQL_FULL)
            except asyncpg.UndefinedColumnError:
                district_rows = await conn.fetch(_DISTRICT_SQL_FALLBACK)

    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error: {exc}") from exc

    features = []
    for row in district_rows:
        d = dict(row)
        geom_str = d.pop("geometry")
        if not geom_str:
            continue
        geom = json.loads(geom_str)

        impacts = calculator.calculate_impacts(
            district=d,
            lca=lca,
            wfh_delta=params.wfh_delta,
            bev_delta=params.bev_delta,
            phev_delta=params.phev_delta,
            ebus_share=params.ebus_share,
            green_elec=params.green_elec,
            auto_besetzung_override=params.auto_besetzung_override,
        )

        effective_trips = float(d["trips_per_day"]) * max(0.01, 1.0 - params.wfh_delta / 3.0)
        base_occ = float(d["auto_besetzung"]) if d.get("auto_besetzung") else 1.4
        eff_occ  = params.auto_besetzung_override if params.auto_besetzung_override is not None else base_occ

        # Flat properties for MapLibre paint expressions
        props: dict = {
            "district_id":    d["district_id"],
            "district_name":  d["district_name"] or d.get("sb_name", ""),
            "sb_name":        d.get("sb_name", ""),
            "trips_per_day":  float(d["trips_per_day"]),
            "effective_trips": round(effective_trips, 2),
            "km_per_trip":    float(d["km_per_trip"]),
            "homeoffice_pct": float(d["homeoffice_pct"]) if d.get("homeoffice_pct") is not None else 0.0,
            "auto_besetzung": base_occ,
            "eff_auto_besetzung": round(eff_occ, 2),
            "split_fuss":     float(d["split_fuss"]),
            "split_rad":      float(d["split_rad"]),
            "split_opnv":     float(d["split_opnv"]),
            "split_auto":     float(d["split_auto"]),
            "population":     d.get("population"),
            "household_size": float(d["household_size"]) if d.get("household_size") is not None else None,
            "car_per_household": float(d["car_per_household"]) if d.get("car_per_household") is not None else None,
            "flaeche_qm":     float(d["flaeche_qm"]) if d.get("flaeche_qm") else None,
        }

        # Add flat per-metric values per category for choropleth
        for cat, vals in impacts.items():
            props[f"per_trip_{cat}"]  = round(vals["per_trip"],  8)
            props[f"per_km_{cat}"]    = round(vals["per_km"],    8)
            props[f"per_day_{cat}"]   = round(vals["per_day"],   8)
            props[f"per_year_{cat}"]  = round(vals["per_year"],  8)

        # Full breakdown as nested object (accessed via featuresByDistId map in JS)
        props["breakdown"] = {
            cat: {
                "per_trip":  round(vals["per_trip"],  6),
                "per_km":    round(vals["per_km"],    6),
                "per_day":   round(vals["per_day"],   6),
                "per_year":  round(vals["per_year"],  6),
                "modes":     vals["modes"],
            }
            for cat, vals in impacts.items()
        }

        features.append({"type": "Feature", "geometry": geom, "properties": props})

    return {"type": "FeatureCollection", "features": features}


# ── Static frontend (must be last) ────────────────────────────────────────────
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.app_host, port=settings.app_port, reload=True)
