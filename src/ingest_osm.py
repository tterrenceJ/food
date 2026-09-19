from pygris import counties
import requests

# Fetch TN counties and filter to Shelby County
tn_counties = counties(state="TN", year=2024, cache=True)
shelby = tn_counties[tn_counties["NAME"] == "Shelby"].to_crs(epsg=4326)

# Extract bounding coordinates
west, south, east, north = shelby.total_bounds
county_bounds = (south, west, north, east)
overpass_url = "https://overpass-api.de/api/interpreter"
south, west, north, east = county_bounds  # from your TIGER/Line county boundary, EPSG:4326

query = f"""
[out:json][timeout:60];
(
  node["shop"~"supermarket|grocery"]({south},{west},{north},{east});
  way["shop"~"supermarket|grocery"]({south},{west},{north},{east});
);
out center;
"""
resp = requests.post(overpass_url, data={"data": query})
