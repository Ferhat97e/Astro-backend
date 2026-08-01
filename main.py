from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from flatlib.datetime import Datetime
from flatlib.geopos import GeoPos
from flatlib.chart import Chart
from flatlib import const

app = FastAPI(title="AEON Astro Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SIGNS_DE = {
    "Aries": "Widder", "Taurus": "Stier", "Gemini": "Zwillinge",
    "Cancer": "Krebs", "Leo": "Löwe", "Virgo": "Jungfrau",
    "Libra": "Waage", "Scorpio": "Skorpion", "Sagittarius": "Schütze",
    "Capricorn": "Steinbock", "Aquarius": "Wassermann", "Pisces": "Fische"
}

SIGN_SYMBOLS = {
    "Widder": "♈", "Stier": "♉", "Zwillinge": "♊", "Krebs": "♋",
    "Löwe": "♌", "Jungfrau": "♍", "Waage": "♎", "Skorpion": "♏",
    "Schütze": "♐", "Steinbock": "♑", "Wassermann": "♒", "Fische": "♓"
}

PLANET_SYMBOLS = {
    "Sun": "☉", "Moon": "☽", "Mercury": "☿", "Venus": "♀",
    "Mars": "♂", "Jupiter": "♃", "Saturn": "♄", "Uranus": "♅",
    "Neptune": "♆", "Pluto": "♇", "North Node": "☊", "South Node": "☋"
}

PLANET_NAMES_DE = {
    "Sun": "Sonne", "Moon": "Mond", "Mercury": "Merkur", "Venus": "Venus",
    "Mars": "Mars", "Jupiter": "Jupiter", "Saturn": "Saturn",
    "Uranus": "Uranus", "Neptune": "Neptun", "Pluto": "Pluto",
    "North Node": "Nordknoten", "South Node": "Südknoten"
}

FLATLIB_PLANETS = [
    const.SUN, const.MOON, const.MERCURY, const.VENUS, const.MARS,
    const.JUPITER, const.SATURN, const.URANUS, const.NEPTUNE, const.PLUTO,
    const.NORTH_NODE
]

class ChartRequest(BaseModel):
    name: str = Field(default="", max_length=100)
    date: str
    time: str
    place: str = Field(default="", max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str
    house_system: Literal["placidus", "koch", "equal", "whole_sign", "regiomontanus", "campanus"] = "placidus"

HOUSE_SYSTEMS = {
    "placidus": const.PLACIDUS,
    "koch": const.KOCH,
    "equal": const.EQUAL,
    "whole_sign": const.WHOLE_SIGN,
    "regiomontanus": const.REGIOMONTANUS,
    "campanus": const.CAMPANUS,
}

def sign_de(sign_en: str) -> str:
    return SIGNS_DE.get(sign_en, sign_en)

def parse_degree(lon: float) -> tuple[int, int, int]:
    deg_in_sign = lon % 30
    d = int(deg_in_sign)
    m = int((deg_in_sign - d) * 60)
    s = int(((deg_in_sign - d) * 60 - m) * 60)
    return d, m, s

def format_planet(p, house_num: int) -> dict:
    lon = p.lon
    sign_en = p.sign
    sign = sign_de(sign_en)
    d, m, s = parse_degree(lon)
    name_de = PLANET_NAMES_DE.get(p.id, p.id)
    symbol = PLANET_SYMBOLS.get(p.id, "★")
    retrograde = hasattr(p, 'movement') and p.movement() == const.RETROGRADE
    return {
        "name": name_de,
        "symbol": symbol,
        "longitude": round(lon, 8),
        "sign": sign,
        "sign_symbol": SIGN_SYMBOLS.get(sign, ""),
        "sign_index": list(SIGNS_DE.values()).index(sign) if sign in SIGNS_DE.values() else 0,
        "degree": d,
        "minute": m,
        "second": s,
        "formatted": f"{d:02d}° {m:02d}′ {s:02d}″ {sign}",
        "retrograde": retrograde,
        "house": house_num,
        "speed": 0,
        "latitude": 0,
        "distance": 0,
        "flags": 0
    }

def get_house_for_planet(lon: float, cusps: list) -> int:
    for i in range(12):
        start = cusps[i] % 360
        end = cusps[(i + 1) % 12] % 360
        d = lon % 360
        if start < end:
            if start <= d < end:
                return i + 1
        else:
            if d >= start or d < end:
                return i + 1
    return 1

@app.get("/")
def index():
    return {"status": "AEON Astro Backend läuft", "version": "1.0"}

@app.get("/api/geocode")
def geocode(place: str) -> dict:
    place = place.strip()
    if len(place) < 2:
        raise HTTPException(status_code=400, detail="Bitte einen gültigen Ort eingeben.")

    encoded = urllib.parse.quote(place)
    url = f"https://nominatim.openstreetmap.org/search?q={encoded}&format=jsonv2&limit=5&addressdetails=1"
    req = urllib.request.Request(url, headers={"User-Agent": "AEONApp/1.0", "Accept-Language": "de"})

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=502, detail="Ortssuche nicht erreichbar.")

    if not data:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden.")

    try:
        from timezonefinder import TimezoneFinder
        tf = TimezoneFinder(in_memory=True)
    except Exception:
        raise HTTPException(status_code=500, detail="TimezoneFinder Fehler.")

    results = []
    for item in data:
        lat = float(item["lat"])
        lon = float(item["lon"])
        tz = tf.timezone_at(lat=lat, lng=lon) or tf.closest_timezone_at(lat=lat, lng=lon) or "UTC"
        results.append({"display_name": item["display_name"], "latitude": lat, "longitude": lon, "timezone": tz})

    return {"results": results}

@app.post("/api/chart")
def chart(payload: ChartRequest) -> dict:
    try:
        local_zone = ZoneInfo(payload.timezone)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Ungültige Zeitzone: {payload.timezone}")

    try:
        local_naive = datetime.fromisoformat(f"{payload.date}T{payload.time}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Datum oder Uhrzeit ungültig.")

    local_dt = local_naive.replace(tzinfo=local_zone)
    utc_dt = local_dt.astimezone(timezone.utc)

    date_str = utc_dt.strftime("%Y/%m/%d")
    time_str = utc_dt.strftime("%H:%M")
    utc_offset = "+00:00"

    try:
        fl_date = Datetime(date_str, time_str, utc_offset)
        fl_pos = GeoPos(payload.latitude, payload.longitude)
        house_sys = HOUSE_SYSTEMS.get(payload.house_system, const.PLACIDUS)
        fl_chart = Chart(fl_date, fl_pos, IDs=FLATLIB_PLANETS, hsys=house_sys)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Berechnungsfehler: {str(e)}")

    # Houses
    houses = []
    cusps = []
    for i in range(1, 13):
        h = fl_chart.get(f"House{i}")
        cusps.append(h.lon)
        d, m, s = parse_degree(h.lon)
        sign = sign_de(h.sign)
        houses.append({
            "house": i,
            "longitude": round(h.lon, 8),
            "sign": sign,
            "sign_symbol": SIGN_SYMBOLS.get(sign, ""),
            "degree": d, "minute": m, "second": s,
            "formatted": f"{d:02d}° {m:02d}′ {s:02d}″ {sign}"
        })

    # Planets
    planets = []
    for pid in FLATLIB_PLANETS:
        try:
            p = fl_chart.get(pid)
            house_num = get_house_for_planet(p.lon, cusps)
            planets.append(format_planet(p, house_num))
        except Exception:
            continue

    # South Node
    north = fl_chart.get(const.NORTH_NODE)
    south_lon = (north.lon + 180) % 360
    d, m, s = parse_degree(south_lon)
    sign = sign_de(fl_chart.get(const.NORTH_NODE).sign)
    south_sign_idx = (list(SIGNS_DE.values()).index(sign_de(north.sign)) + 6) % 12
    south_sign = list(SIGNS_DE.values())[south_sign_idx]
    planets.append({
        "name": "Südknoten", "symbol": "☋",
        "longitude": round(south_lon, 8),
        "sign": south_sign,
        "sign_symbol": SIGN_SYMBOLS.get(south_sign, ""),
        "sign_index": south_sign_idx,
        "degree": d, "minute": m, "second": s,
        "formatted": f"{d:02d}° {m:02d}′ {s:02d}″ {south_sign}",
        "retrograde": False, "house": get_house_for_planet(south_lon, cusps),
        "speed": 0, "latitude": 0, "distance": 0, "flags": 0
    })

    # Angles
    asc = fl_chart.get(const.ASC)
    mc = fl_chart.get(const.MC)
    desc_lon = (asc.lon + 180) % 360
    ic_lon = (mc.lon + 180) % 360

    def make_angle(name, symbol, lon):
        d, m, s = parse_degree(lon)
        sign_idx = int(lon // 30)
        sign = list(SIGNS_DE.values())[sign_idx]
        return {
            "name": name, "symbol": symbol,
            "longitude": round(lon, 8), "sign": sign,
            "sign_symbol": SIGN_SYMBOLS.get(sign, ""),
            "sign_index": sign_idx,
            "degree": d, "minute": m, "second": s,
            "formatted": f"{d:02d}° {m:02d}′ {s:02d}″ {sign}"
        }

    angles = {
        "ascendant": make_angle("Aszendent", "AC", asc.lon),
        "descendant": make_angle("Deszendent", "DC", desc_lon),
        "medium_coeli": make_angle("Medium Coeli", "MC", mc.lon),
        "imum_coeli": make_angle("Imum Coeli", "IC", ic_lon),
        "vertex": make_angle("Vertex", "Vx", desc_lon),
    }

    return {
        "subject": {
            "name": payload.name,
            "date": payload.date,
            "time": payload.time,
            "place": payload.place,
            "latitude": payload.latitude,
            "longitude": payload.longitude,
            "timezone": payload.timezone,
            "house_system": payload.house_system,
            "local_datetime": local_dt.isoformat(),
            "utc_datetime": utc_dt.isoformat(),
        },
        "planets": planets,
        "houses": houses,
        "angles": angles,
        "aspects": []
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
