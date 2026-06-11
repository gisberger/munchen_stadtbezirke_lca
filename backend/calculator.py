"""
LCA impact calculator per Munich Stadtbezirk.

Mode names in lca.lca_per_pkm
──────────────────────────────
Auto  : auto_benzin, auto_diesel, auto_hybrid_conv/green, auto_strom_conv/green
Bus   : bus_diesel, bus_strom_conv/green
Rail  : ubahn_conv/green, sbahn_conv/green, tram_conv/green
Cycle : bike  (walking has no LCA entry → zero impact)

District shares in lca.district_base are stored as PERCENTAGES (0–100).

Occupancy scaling: lca_per_pkm for auto is interpreted as already normalised to
per person-km at the district's baseline auto_besetzung. Changing occupancy via
the slider scales the auto contribution proportionally.
"""

from typing import Any

LcaData = dict[str, dict[str, float]]   # {mode: {impact_category: result_per_pkm}}
DistrictRow = dict[str, Any]


def _pct(value: Any) -> float:
    """Convert a stored percentage (0–100) to a fraction (0–1)."""
    return float(value) / 100.0


def calculate_impacts(
    district: DistrictRow,
    lca: LcaData,
    wfh_delta: float,                       # fraction; only 1/3 of trips are affected
    bev_delta: float,                       # percentage-point delta on BEV share (0.20 = +20pp)
    phev_delta: float,                      # percentage-point delta on PHEV share
    ebus_share: float,                     # 0–1 fraction of bus fleet that is electric
    green_elec: bool,                      # use _green vs _conv LCA variants
    auto_besetzung_override: float | None, # None = use district value
) -> dict[str, dict]:
    """
    Returns:
        {
          impact_category: {
            'per_trip':  float,
            'per_km':    float,
            'per_day':   float,
            'per_year':  float,
            'modes': {
              'fuss': {'trip_share': float, 'per_trip': float, 'pct': float},
              'rad':  {'trip_share': float, 'per_trip': float, 'pct': float},
              'opnv': {'trip_share': float, 'per_trip': float, 'pct': float,
                       'sub': {
                         'ubahn': {'share': float, 'per_trip': float},
                         'sbahn': ..., 'bus': ..., 'tram': ...
                       }},
              'auto': {'trip_share': float, 'per_trip': float, 'pct': float},
            }
          }
        }
    """

    km = float(district["km_per_trip"])
    # WFH only affects the commute portion (~1/3 of all trips)
    effective_trips = float(district["trips_per_day"]) * max(0.01, 1.0 - wfh_delta / 3.0)

    # ── Occupancy scaling ────────────────────────────────────────────────────
    base_occ = float(district["auto_besetzung"]) if district.get("auto_besetzung") else 1.4
    new_occ  = auto_besetzung_override if auto_besetzung_override is not None else base_occ
    # If occupancy increases → per-person auto impact decreases proportionally
    occ_scale = base_occ / max(0.1, new_occ)

    # ── Modal split (% → fraction) ────────────────────────────────────────────
    sf = _pct(district["split_fuss"])
    sr = _pct(district["split_rad"])
    so = _pct(district["split_opnv"])
    sa = _pct(district["split_auto"])

    # ── ÖPNV sub-split ────────────────────────────────────────────────────────
    sh_ubahn = _pct(district["opnv_share_ubahn"])
    sh_sbahn = _pct(district["opnv_share_sbahn"])
    sh_bus   = _pct(district["opnv_share_bus"])
    sh_tram  = _pct(district["opnv_share_tram"])

    # ── Auto fleet mix ────────────────────────────────────────────────────────
    a_benzin_0 = _pct(district["auto_share_benzin"])
    a_diesel_0 = _pct(district["auto_share_diesel"])
    a_phev_0   = _pct(district["auto_share_phev"])
    a_elec_0   = _pct(district["auto_share_elektro"])

    # Apply percentage-point deltas, clamp to [0, 1]
    a_elec = min(1.0, max(0.0, a_elec_0 + bev_delta))
    a_phev = min(1.0, max(0.0, a_phev_0 + phev_delta))

    # If combined BEV+PHEV exceeds 100%, scale them back proportionally
    if a_elec + a_phev > 1.0:
        total_ep = a_elec + a_phev
        a_elec /= total_ep
        a_phev /= total_ep

    # Distribute remaining share to benzin/diesel in their original ratio
    remaining = max(0.0, 1.0 - a_elec - a_phev)
    fossil = a_benzin_0 + a_diesel_0
    if fossil > 1e-6:
        a_benzin = remaining * a_benzin_0 / fossil
        a_diesel = remaining * a_diesel_0 / fossil
    else:
        a_benzin = remaining * 0.5
        a_diesel = remaining * 0.5

    esuf = "_green" if green_elec else "_conv"

    def lv(mode: str, cat: str) -> float:
        return lca.get(mode, {}).get(cat, 0.0)

    # ── Iterate over every impact category ───────────────────────────────────
    categories: set[str] = set()
    for cats in lca.values():
        categories.update(cats.keys())

    results: dict[str, dict] = {}

    for cat in categories:
        # Walking: no LCA entry → 0
        fuss_lca = 0.0

        # Cycling (all cycling treated as conventional bike)
        rad_lca = lv("bike", cat)

        # ÖPNV sub-modes
        ubahn_lca = lv("ubahn" + esuf, cat)
        sbahn_lca = lv("sbahn" + esuf, cat)
        tram_lca  = lv("tram"  + esuf, cat)
        bus_lca   = (
            (1.0 - ebus_share) * lv("bus_diesel", cat)
            + ebus_share       * lv("bus_strom" + esuf, cat)
        )
        opnv_lca = (
            sh_ubahn * ubahn_lca
            + sh_sbahn * sbahn_lca
            + sh_bus   * bus_lca
            + sh_tram  * tram_lca
        )

        # Auto (apply occupancy scaling)
        auto_lca = occ_scale * (
            a_benzin * lv("auto_benzin",      cat)
            + a_diesel * lv("auto_diesel",    cat)
            + a_phev   * lv("auto_hybrid" + esuf, cat)
            + a_elec   * lv("auto_strom"  + esuf, cat)
        )

        # Per-mode contribution to per-trip impact (modal_share × lca × km)
        fuss_trip = sf * fuss_lca * km
        rad_trip  = sr * rad_lca  * km
        opnv_trip = so * opnv_lca * km
        auto_trip = sa * auto_lca * km

        total = fuss_trip + rad_trip + opnv_trip + auto_trip

        def pct_of(v: float) -> float:
            return round(100.0 * v / total, 1) if total > 1e-15 else 0.0

        results[cat] = {
            "per_trip": total,
            "per_km":   total / km if km > 0 else 0.0,
            "per_day":  total * effective_trips,
            "per_year": total * effective_trips * 365.0,
            "modes": {
                "fuss": {
                    "trip_share": round(sf * 100, 1),
                    "per_trip":   round(fuss_trip, 8),
                    "pct":        pct_of(fuss_trip),
                },
                "rad": {
                    "trip_share": round(sr * 100, 1),
                    "per_trip":   round(rad_trip, 8),
                    "pct":        pct_of(rad_trip),
                },
                "opnv": {
                    "trip_share": round(so * 100, 1),
                    "per_trip":   round(opnv_trip, 8),
                    "pct":        pct_of(opnv_trip),
                    "sub": {
                        "ubahn": {
                            "share":    round(sh_ubahn * 100, 1),
                            "per_trip": round(so * sh_ubahn * ubahn_lca * km, 8),
                        },
                        "sbahn": {
                            "share":    round(sh_sbahn * 100, 1),
                            "per_trip": round(so * sh_sbahn * sbahn_lca * km, 8),
                        },
                        "bus": {
                            "share":    round(sh_bus * 100, 1),
                            "per_trip": round(so * sh_bus * bus_lca * km, 8),
                        },
                        "tram": {
                            "share":    round(sh_tram * 100, 1),
                            "per_trip": round(so * sh_tram * tram_lca * km, 8),
                        },
                    },
                },
                "auto": {
                    "trip_share": round(sa * 100, 1),
                    "per_trip":   round(auto_trip, 8),
                    "pct":        pct_of(auto_trip),
                },
            },
        }

    return results
