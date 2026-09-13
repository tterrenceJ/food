import requests
API_KEY="5135c331d73d73f2a2e60f2611dfeed21b0f5024"
STATE, COUNTY = "47", "157"  # Tennessee, Shelby County
vars_="NAME,B01003_001E,B17001_001E,B17001_002E,B25044_001E,B25044_003E,B25044_010E"
url=("https://api.census.gov/data/2024/acs/acs5"
     f"?get={vars_}&for=block%20group:*"
     f"&in=state:{STATE}%20county:{COUNTY}%20tract:*&key={API_KEY}"
     )
resp = requests.get(url).json()