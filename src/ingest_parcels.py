from pygris import block_groups, tracts
import geopandas as gpd
bg = block_groups(state="TN", county="Shelby", year=2024, cache=True)
tr = tracts(state="TN", county="Shelby", year=2024, cache=True)

parcels = gpd.read_file(
    "https://gis.shelbycountytn.gov/public/rest/services/BaseMap/Assessor/MapServer/0/query"
    "?where=1%3D1&outFields=*&f=geojson"
)