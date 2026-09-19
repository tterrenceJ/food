"""
build_demand.py — Phase 2: build the demand-node table (proposal §1, §3).

Input:  data/raw/acs_block_groups_<year>.csv     (from ingest_census.py)
        data/raw/tiger_block_groups_<year>.gpkg  (from ingest_census.py)
Output: data/processed/demand_nodes.csv
        columns: block_group_id, tract_id, lat, lon, population, poverty_rate, pct_no_vehicle
        (population is h_i in the model's notation — named `population` here since
        that's what the proposal's own Phase 2 checklist calls the output column)

This is the phase the tutorial gives you a 4-line snippet for and leaves the rest
implied. The actual work is below, split into small functions so each piece —
GEOID reconstruction, the two rate calculations, the centroid reprojection — is
independently testable. tests/test_build_demand.py exercises every one of them
against tiny synthetic fixtures (NOT Memphis data — 3 fake block groups with round
numbers, so nobody mistakes fixture output for a real result).

Two things worth knowing before you trust this on the real pull:

1. GEOID reconstruction. The Census API returns state/county/tract/block-group as
   four separate zero-padded STRING columns, not a combined ID. TIGER's own GEOID
   column is their concatenation: state(2) + county(3) + tract(6) + block group(1)
   = 12 characters. ingest_census.py already preserves the zero-padding on the way
   out; reconstruct_geoid() below re-derives it the same way on the way back in,
   with an explicit dtype=str on load so pandas never gets a chance to infer these
   as integers and eat a leading zero (the same failure mode documented at length
   in ingest_fara.py, from a bug that was real and observed on this project's
   other data source).

2. Safe division. poverty_rate and pct_no_vehicle both divide by an ACS universe
   count that is occasionally 0 (parks, industrial-only block groups, etc.) or NaN
   (suppressed for disclosure-avoidance). Both compute a NaN rather than raising or
   silently emitting 0/0 -> 0, and the row count with each is reported so it ends
   up in your write-up as a real caveat (per the tutorial's own "ACS margins of
   error" pitfall) instead of a silent gap.

Usage:
    python src/build_demand.py
    python src/build_demand.py --year 2024 --crs EPSG:3857
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "raw"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "processed"
DEFAULT_YEAR = 2024

OUTPUT_COLUMNS = ["block_group_id", "tract_id", "lat", "lon", "population", "poverty_rate", "pct_no_vehicle"]


def reconstruct_geoid(acs_df: pd.DataFrame) -> pd.DataFrame:
    """state(2)+county(3)+tract(6)+block group(1) -> 12-char GEOID, matching TIGER."""
    df = acs_df.copy()
    for col, width in [("state", 2), ("county", 3), ("tract", 6), ("block group", 1)]:
        if col not in df.columns:
            raise KeyError(f"Expected column {col!r} from the Census API response; got {list(df.columns)}")
        df[col] = df[col].astype(str).str.zfill(width)
    df["GEOID"] = df["state"] + df["county"] + df["tract"] + df["block group"]
    bad_width = df["GEOID"].str.len() != 12
    if bad_width.any():
        raise ValueError(f"{bad_width.sum()} reconstructed GEOIDs aren't 12 characters — check zero-padding upstream.")
    return df


def compute_poverty_rate(df: pd.DataFrame) -> pd.DataFrame:
    """poverty_count / poverty_universe. NaN (not 0) when the universe is 0 or NaN —
    a block group with a zero poverty universe has an undefined rate, not a 0% one."""
    df = df.copy()
    universe = df["poverty_universe"]
    safe_universe = universe.where(universe > 0)  # 0 or negative -> NaN before dividing
    df["poverty_rate"] = df["poverty_count"] / safe_universe
    n_undefined = df["poverty_rate"].isna().sum()
    if n_undefined:
        print(f"[build_demand] poverty_rate undefined (zero/NaN poverty universe) for {n_undefined} block group(s).")
    return df


def compute_pct_no_vehicle(df: pd.DataFrame) -> pd.DataFrame:
    """(owner-occupied + renter-occupied, no vehicle) / total occupied units. Same
    zero-universe-> NaN guard as poverty_rate, same reasoning."""
    df = df.copy()
    total = df["occupied_units_total"]
    safe_total = total.where(total > 0)
    no_vehicle = df["owner_occupied_no_vehicle"] + df["renter_occupied_no_vehicle"]
    df["pct_no_vehicle"] = no_vehicle / safe_total
    n_undefined = df["pct_no_vehicle"].isna().sum()
    if n_undefined:
        print(f"[build_demand] pct_no_vehicle undefined (zero/NaN occupied units) for {n_undefined} block group(s).")
    return df


def compute_centroids(bg_gdf: gpd.GeoDataFrame, projected_crs: str) -> gpd.GeoDataFrame:
    """Reproject to a projected CRS before centroids (unprojected lat/lon centroids
    are distorted — the tutorial's own Phase 2 checklist item), then reproject the
    centroid back to EPSG:4326 for haversine use downstream in Phase 5."""
    gdf = bg_gdf.copy()
    projected = gdf.to_crs(projected_crs)
    centroid_projected = projected.geometry.centroid
    centroid_lonlat = gpd.GeoSeries(centroid_projected, crs=projected_crs).to_crs("EPSG:4326")
    gdf["lat"] = centroid_lonlat.y.values
    gdf["lon"] = centroid_lonlat.x.values
    return gdf


def build_demand_table(acs_df: pd.DataFrame, bg_gdf: gpd.GeoDataFrame, projected_crs: str = "EPSG:3857") -> pd.DataFrame:
    """The full Phase 2 pipeline as one pure function: GEOID join + both rate
    calculations + centroid reprojection -> the exact output schema. Takes
    already-loaded frames (not file paths) so it's directly unit-testable."""
    acs = reconstruct_geoid(acs_df)
    acs = compute_poverty_rate(acs)
    acs = compute_pct_no_vehicle(acs)

    if "GEOID" not in bg_gdf.columns:
        raise KeyError(f"Expected a GEOID column on the TIGER block-group layer; got {list(bg_gdf.columns)}")
    bg = compute_centroids(bg_gdf, projected_crs)

    merged = bg[["GEOID", "lat", "lon"]].merge(
        acs[["GEOID", "population_total", "poverty_rate", "pct_no_vehicle"]],
        on="GEOID", how="outer", indicator=True,
    )

    only_tiger = (merged["_merge"] == "left_only").sum()
    only_acs = (merged["_merge"] == "right_only").sum()
    if only_tiger:
        print(f"[build_demand] WARNING: {only_tiger} block group(s) in TIGER have no matching ACS row — "
              f"dropped from output. Likely a year mismatch between the TIGER and ACS pulls.")
    if only_acs:
        print(f"[build_demand] WARNING: {only_acs} block group(s) in ACS have no matching TIGER geometry — "
              f"dropped from output. Likely a year mismatch between the TIGER and ACS pulls.")

    merged = merged[merged["_merge"] == "both"].drop(columns="_merge")

    out = pd.DataFrame({
        "block_group_id": merged["GEOID"],
        "tract_id": merged["GEOID"].str[:11],
        "lat": merged["lat"],
        "lon": merged["lon"],
        "population": merged["population_total"],
        "poverty_rate": merged["poverty_rate"],
        "pct_no_vehicle": merged["pct_no_vehicle"],
    })
    return out[OUTPUT_COLUMNS].sort_values("block_group_id").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--crs", default="EPSG:3857", help="Projected CRS for centroid computation")
    args = parser.parse_args()

    acs_path = args.raw_dir / f"acs_block_groups_{args.year}.csv"
    tiger_path = args.raw_dir / f"tiger_block_groups_{args.year}.gpkg"
    for p in (acs_path, tiger_path):
        if not p.exists():
            raise SystemExit(
                f"Missing {p}. Run ingest_census.py first (needs a live Census API key + network "
                f"this sandbox doesn't have — see README)."
            )

    print(f"[build_demand] Loading {acs_path} ...")
    acs_df = pd.read_csv(acs_path, dtype={"state": str, "county": str, "tract": str, "block group": str})

    print(f"[build_demand] Loading {tiger_path} ...")
    bg_gdf = gpd.read_file(tiger_path)

    print(f"[build_demand] Building demand table (centroids in {args.crs}) ...")
    demand = build_demand_table(acs_df, bg_gdf, projected_crs=args.crs)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / "demand_nodes.csv"
    demand.to_csv(out_path, index=False)

    print(f"[build_demand] -> {len(demand)} block groups -> {out_path}")
    print(f"[build_demand] -> total population (sum of h_i): {demand['population'].sum():,.0f}")
    print(f"[build_demand] -> {demand['tract_id'].nunique()} distinct tracts represented")


if __name__ == "__main__":
    main()