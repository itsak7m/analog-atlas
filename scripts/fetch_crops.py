"""Nutrients of candidate space crops from USDA FoodData Central (SR Legacy, raw foods, per 100 g).

Downloads each food once into data/raw/crops/<crop>.json (kept, so the numbers can be checked),
then writes data/crops.json for the app. Run: python -I scripts/fetch_crops.py

Source: the FoodData Central record of each food (https://fdc.nal.usda.gov/food-details/<id>/nutrients),
read through the JSON that the FoodData Central web page itself loads (no API key needed).
Records that came from the FDC API (DEMO_KEY) have the same numbers and are read the same way.
"""
import json, os, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RAW = os.path.join(ROOT, "data", "raw", "crops")
# crop id: (FoodData Central id, the description it must start with)
IDS = {
    "potato": (170026, "Potatoes, flesh and skin, raw"),
    "sweet-potato": (168482, "Sweet potato, raw, unprepared"),
    "soybean": (174270, "Soybeans, mature seeds, raw"),
    "wheat": (168890, "Wheat, hard red winter"),
    "peanut": (172430, "Peanuts, all types, raw"),
    "lettuce": (169249, "Lettuce, green leaf, raw"),
    "tomato": (170457, "Tomatoes, red, ripe, raw, year round average"),
    "rice": (169703, "Rice, brown, long-grain, raw"),
}
# FoodData Central nutrient numbers
NUM = {"kcal": "208", "protein_g": "203", "fat_g": "204", "carbs_g": "205", "fiber_g": "291", "vitc_mg": "401", "potassium_mg": "306"}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (analog-atlas data script)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def values(food):
    out = {}
    for x in food.get("foodNutrients", []):
        n = x.get("nutrient", {})
        v = x.get("amount", x.get("value"))
        for key, num in NUM.items():
            if n.get("number") == num and v is not None and key not in out:
                out[key] = v
    return out


os.makedirs(RAW, exist_ok=True)
crops = {}
for cid, (fdc, desc) in IDS.items():
    path = os.path.join(RAW, f"{cid}.json")
    if not os.path.exists(path):
        json.dump(get(f"https://fdc.nal.usda.gov/portal-data/external/{fdc}"), open(path, "w", encoding="utf-8"), indent=1)
    food = json.load(open(path, encoding="utf-8"))
    assert food.get("fdcId") == fdc and food.get("description", "").startswith(desc), (cid, food.get("description"))
    v = values(food)
    missing = [k for k in NUM if k not in v]
    crops[cid] = {"fdcId": fdc, "description": desc, "per100g": {k: v.get(k) for k in NUM},
                  "url": f"https://fdc.nal.usda.gov/food-details/{fdc}/nutrients", "raw": f"data/raw/crops/{cid}.json"}
    print(f"{cid:13} {fdc}  " + "  ".join(f"{k}={v.get(k)}" for k in NUM) + (f"  MISSING {missing}" if missing else ""))

doc = {
    "about": "Nutrients per 100 g of the raw food, from USDA FoodData Central (SR Legacy). Values as published; null = not in the record.",
    "source": {"label": "U.S. Department of Agriculture, FoodData Central (SR Legacy)", "url": "https://fdc.nal.usda.gov/"},
    "made_by": "scripts/fetch_crops.py",
    "crops": crops,
}
json.dump(doc, open(os.path.join(ROOT, "data", "crops.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("wrote data/crops.json")
