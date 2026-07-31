from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

import swisseph as swe
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Radix Calculator")

swe.set_ephe_path("")

SIGNS = [
"Widder",
"Stier",
"Zwillinge",
"Krebs",
"Löwe",
"Jungfrau",
"Waage",
"Skorpion",
"Schütze",
"Steinbock",
"Wassermann",
"Fische",
]

SIGN_SYMBOLS = [
"♈",
"♉",
"♊",
"♋",
"♌",
"♍",
"♎",
"♏",
"♐",
"♑",
"♒",
"♓",
]

PLANETS = {
"Sonne": {"id": swe.SUN, "symbol": "☉"},
"Mond": {"id": swe.MOON, "symbol": "☽"},
"Merkur": {"id": swe.MERCURY, "symbol": "☿"},
"Venus": {"id": swe.VENUS, "symbol": "♀"},
"Mars": {"id": swe.MARS, "symbol": "♂"},
"Jupiter": {"id": swe.JUPITER, "symbol": "♃"},
"Saturn": {"id": swe.SATURN, "symbol": "♄"},
"Uranus": {"id": swe.URANUS, "symbol": "♅"},
"Neptun": {"id": swe.NEPTUNE, "symbol": "♆"},
"Pluto": {"id": swe.PLUTO, "symbol": "♇"},
"Nordknoten": {"id": swe.TRUE_NODE, "symbol": "☊"},
}

HOUSE_SYSTEMS = {
"placidus": b"P",
"koch": b"K",
"equal": b"E",
"whole_sign": b"W",
"regiomontanus": b"R",
"campanus": b"C",
}

ASPECTS = [
{"name": "Konjunktion", "angle": 0.0, "orb": 8.0, "symbol": "☌"},
{"name": "Sextil", "angle": 60.0, "orb": 5.0, "symbol": "⚹"},
{"name": "Quadrat", "angle": 90.0, "orb": 7.0, "symbol": "□"},
{"name": "Trigon", "angle": 120.0, "orb": 7.0, "symbol": "△"},
{"name": "Quinkunx", "angle": 150.0, "orb": 3.0, "symbol": "⚻"},
{"name": "Opposition", "angle": 180.0, "orb": 8.0, "symbol": "☍"},
]

class ChartRequest(BaseModel):
name: str = Field(default="", max_length=100)
date: str
time: str
place: str = Field(default="", max_length=200)
latitude: float = Field(ge=-90, le=90)
longitude: float = Field(ge=-180, le=180)
timezone: str
house_system: Literal[
"placidus",
"koch",
"equal",
"whole_sign",
"regiomontanus",
"campanus",
 ] = "placidus"

def normalize_degree(value: float) -> float:
return value % 360.0

def angle_distance(a: float, b: float) -> float:
difference = abs(normalize_degree(a) - normalize_degree(b))
return min(difference, 360.0 - difference)

def degree_parts(value: float) -> tuple[int, int, int]:
value = value % 30.0
degrees = int(value)
minutes_float = (value - degrees) * 60.0
minutes = int(minutes_float)
seconds = int(round((minutes_float - minutes) * 60.0))

if seconds == 60:
seconds = 0
minutes += 1

if minutes == 60:
minutes = 0
degrees += 1

return degrees, minutes, seconds

def longitude_data(longitude: float) -> dict:
longitude = normalize_degree(longitude)
sign_index = int(longitude // 30)
degree, minute, second = degree_parts(longitude)

return {
"longitude": round(longitude, 8),
"sign": SIGNS[sign_index],
"sign_symbol": SIGN_SYMBOLS[sign_index],
"sign_index": sign_index,
"degree": degree,
"minute": minute,
"second": second,
"formatted": f"{degree:02d}° {minute:02d}′ {second:02d}″ {SIGNS[sign_index]}",
}

def zodiac_house(longitude: float, cusps: list[float]) -> int:
longitude = normalize_degree(longitude)

for index in range(12):
start = normalize_degree(cusps[index])
end = normalize_degree(cusps[(index + 1) % 12])

if start < end:
if start <= longitude < end:
return index + 1
else:
if longitude >= start or longitude < end:
return index + 1

return 12

def local_datetime_to_julian_day(
date_string: str,
time_string: str,
timezone_name: str,
) -> tuple[float, datetime, datetime]:
try:
local_zone = ZoneInfo(timezone_name)
except Exception as error:
raise HTTPException(
status_code=400,
detail=f"Ungültige Zeitzone: {timezone_name}",
) from error

try:
local_naive = datetime.fromisoformat(f"{date_string}T{time_string}")
except ValueError as error:
raise HTTPException(
status_code=400,
detail="Datum oder Uhrzeit ist ungültig.",
) from error

local_datetime = local_naive.replace(tzinfo=local_zone)
utc_datetime = local_datetime.astimezone(timezone.utc)

decimal_hour = (
utc_datetime.hour
+ utc_datetime.minute / 60.0
+ utc_datetime.second / 3600.0
+ utc_datetime.microsecond / 3_600_000_000.0
)

julian_day = swe.julday(
utc_datetime.year,
utc_datetime.month,
utc_datetime.day,
decimal_hour,
swe.GREG_CAL,
)

return julian_day, local_datetime, utc_datetime

def calculate_planets(julian_day: float) -> list[dict]:
flags = swe.FLG_SWIEPH | swe.FLG_SPEED
results: list[dict] = []

for name, planet in PLANETS.items():
try:
values, returned_flags = swe.calc_ut(
julian_day,
planet["id"],
flags,
)
except swe.Error:
values, returned_flags = swe.calc_ut(
julian_day,
planet["id"],
swe.FLG_MOSEPH | swe.FLG_SPEED,
)

longitude = normalize_degree(values[0])
speed = values[3]
position = longitude_data(longitude)

results.append(
{
"name": name,
"symbol": planet["symbol"],
**position,
"latitude": round(values[1], 8),
"distance": round(values[2], 8),
"speed": round(speed, 8),
"retrograde": speed < 0,
"flags": returned_flags,
}
)

south_node = normalize_degree(
next(
item["longitude"]
for item in results
if item["name"] == "Nordknoten"
)
+ 180.0
)

results.append(
{
"name": "Südknoten",
"symbol": "☋",
**longitude_data(south_node),
"latitude": 0,
"distance": 0,
"speed": 0,
"retrograde": False,
"flags": 0,
}
)

return results

def calculate_houses(
julian_day: float,
latitude: float,
longitude: float,
house_system: str,
) -> tuple[list[dict], dict]:
house_code = HOUSE_SYSTEMS[house_system]

try:
cusps_raw, ascmc = swe.houses_ex(
julian_day,
latitude,
longitude,
house_code,
swe.FLG_SWIEPH,
)
except swe.Error as error:
raise HTTPException(
status_code=400,
detail=(
"Das gewählte Häusersystem konnte für diese geografische "
"Breite nicht berechnet werden."
),
) from error

cusps = list(cusps_raw)

if len(cusps) == 13:
cusps = cusps[1:13]
else:
cusps = cusps[:12]

houses = []

for index, cusp in enumerate(cusps):
houses.append(
{
"house": index + 1,
**longitude_data(cusp),
}
)

ascendant = normalize_degree(ascmc[0])
medium_coeli = normalize_degree(ascmc[1])
armc = normalize_degree(ascmc[2])
vertex = normalize_degree(ascmc[3])

angles = {
"ascendant": {
"name": "Aszendent",
"symbol": "AC",
**longitude_data(ascendant),
},
"descendant": {
"name": "Deszendent",
"symbol": "DC",
**longitude_data(ascendant + 180.0),
},
"medium_coeli": {
"name": "Medium Coeli",
"symbol": "MC",
**longitude_data(medium_coeli),
},
"imum_coeli": {
"name": "Imum Coeli",
"symbol": "IC",
**longitude_data(medium_coeli + 180.0),
},
"vertex": {
"name": "Vertex",
"symbol": "Vx",
**longitude_data(vertex),
},
"armc": round(armc, 8),
}

return houses, angles

def calculate_aspects(planets: list[dict]) -> list[dict]:
aspects: list[dict] = []

excluded_pairs = {
frozenset(("Nordknoten", "Südknoten")),
}

for first_index in range(len(planets)):
for second_index in range(first_index + 1, len(planets)):
first = planets[first_index]
second = planets[second_index]

if frozenset((first["name"], second["name"])) in excluded_pairs:
continue

distance = angle_distance(
first["longitude"],
second["longitude"],
)

for aspect in ASPECTS:
orb = abs(distance - aspect["angle"])

if orb <= aspect["orb"]:
orb_degree, orb_minute, orb_second = degree_parts(orb)

aspects.append(
{
"planet1": first["name"],
"planet1_symbol": first["symbol"],
"planet2": second["name"],
"planet2_symbol": second["symbol"],
"aspect": aspect["name"],
"symbol": aspect["symbol"],
"exact_angle": aspect["angle"],
"actual_angle": round(distance, 8),
"orb": round(orb, 8),
"orb_formatted": (
f"{orb_degree:02d}° "
f"{orb_minute:02d}′ "
f"{orb_second:02d}″"
),
}
)
break

aspects.sort(key=lambda item: item["orb"])
return aspects

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
return HTMLResponse(HTML)

@app.get("/api/geocode")
def geocode(place: str) -> dict:
place = place.strip()

if len(place) < 2:
raise HTTPException(
status_code=400,
detail="Bitte einen gültigen Ort eingeben.",
)

encoded_place = urllib.parse.quote(place)
url = (
"https://nominatim.openstreetmap.org/search"
f"?q={encoded_place}&format=jsonv2&limit=5&addressdetails=1"
)

request = urllib.request.Request(
url,
headers={
"User-Agent": "RadixCalculator/1.0",
"Accept-Language": "de",
},
)

try:
with urllib.request.urlopen(request, timeout=10) as response:
data = json.loads(response.read().decode("utf-8"))
except Exception as error:
raise HTTPException(
status_code=502,
detail="Die Ortssuche ist derzeit nicht erreichbar.",
) from error

if not data:
raise HTTPException(
status_code=404,
detail="Ort wurde nicht gefunden.",
)

try:
from timezonefinder import TimezoneFinder

timezone_finder = TimezoneFinder(in_memory=True)
except Exception as error:
raise HTTPException(
status_code=500,
detail="TimezoneFinder konnte nicht geladen werden.",
) from error

results = []

for item in data:
latitude = float(item["lat"])
longitude = float(item["lon"])
timezone_name = timezone_finder.timezone_at(
lat=latitude,
lng=longitude,
)

if timezone_name is None:
timezone_name = timezone_finder.closest_timezone_at(
lat=latitude,
lng=longitude,
)

results.append(
{
"display_name": item["display_name"],
"latitude": latitude,
"longitude": longitude,
"timezone": timezone_name or "UTC",
}
)

return {"results": results}

@app.post("/api/chart")
def chart(payload: ChartRequest) -> dict:
julian_day, local_datetime, utc_datetime = local_datetime_to_julian_day(
payload.date,
payload.time,
payload.timezone,
)

planets = calculate_planets(julian_day)
houses, angles = calculate_houses(
julian_day,
payload.latitude,
payload.longitude,
payload.house_system,
)

cusp_longitudes = [house["longitude"] for house in houses]

for planet in planets:
planet["house"] = zodiac_house(
planet["longitude"],
cusp_longitudes,
)

aspects = calculate_aspects(planets)

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
"local_datetime": local_datetime.isoformat(),
"utc_datetime": utc_datetime.isoformat(),
"julian_day": round(julian_day, 8),
},
"planets": planets,
"houses": houses,
"angles": angles,
"aspects": aspects,
}

HTML = r"""
<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta
name="viewport"
content="width=device-width, initial-scale=1"
>
<title>Geburtshoroskop-Rechner</title>

<style>
:root {
color-scheme: dark;
--background: #080911;
--surface: #11131f;
--surface-2: #181b2b;
--border: #2a2e45;
--text: #f2f3f8;
--muted: #9ba1b8;
--accent: #b99cff;
--accent-2: #6ee7ff;
--danger: #ff7b8e;
--success: #78e6ae;
--gold: #efcb78;
}

* {
box-sizing: border-box;
}

body {
margin: 0;
min-height: 100vh;
background:
radial-gradient(
circle at 10% 0%,
rgba(100, 74, 180, 0.22),
transparent 35%
),
radial-gradient(
circle at 90% 10%,
rgba(35, 144, 180, 0.14),
transparent 30%
),
var(--background);
color: var(--text);
font-family:
Inter,
ui-sans-serif,
system-ui,
-apple-system,
BlinkMacSystemFont,
"Segoe UI",
sans-serif;
}

button,
input,
select {
font: inherit;
}

.app {
width: min(1500px, calc(100% - 32px));
margin: 0 auto;
padding: 32px 0 80px;
}

.header {
margin-bottom: 24px;
}

.header h1 {
margin: 0;
font-size: clamp(28px, 5vw, 48px);
letter-spacing: -0.04em;
}

.header p {
margin: 10px 0 0;
color: var(--muted);
}

.layout {
display: grid;
grid-template-columns: minmax(280px, 380px) minmax(0, 1fr);
gap: 24px;
align-items: start;
}

.card {
border: 1px solid var(--border);
border-radius: 20px;
background: rgba(17, 19, 31, 0.9);
box-shadow: 0 20px 60px rgba(0, 0, 0, 0.25);
backdrop-filter: blur(18px);
}

.form-card {
padding: 22px;
position: sticky;
top: 16px;
}

.form-grid {
display: grid;
gap: 16px;
}

.field {
display: grid;
gap: 7px;
}

.field-row {
display: grid;
grid-template-columns: 1fr 1fr;
gap: 12px;
}

label {
color: var(--muted);
font-size: 13px;
font-weight: 700;
letter-spacing: 0.02em;
}

input,
select {
width: 100%;
min-height: 46px;
padding: 10px 12px;
color: var(--text);
border: 1px solid var(--border);
border-radius: 12px;
outline: none;
background: var(--surface-2);
}

input:focus,
select:focus {
border-color: var(--accent);
box-shadow: 0 0 0 3px rgba(185, 156, 255, 0.12);
}

.place-wrapper {
position: relative;
}

.place-row {
display: grid;
grid-template-columns: 1fr auto;
gap: 8px;
}

button {
min-height: 46px;
padding: 10px 16px;
border: 0;
border-radius: 12px;
cursor: pointer;
font-weight: 800;
}

button:disabled {
opacity: 0.55;
cursor: wait;
}

.secondary-button {
color: var(--text);
background: var(--surface-2);
border: 1px solid var(--border);
}

.primary-button {
color: #11131f;
background: linear-gradient(
135deg,
var(--accent),
var(--accent-2)
);
}

.results-list {
position: absolute;
z-index: 20;
top: calc(100% + 6px);
left: 0;
right: 0;
display: none;
max-height: 260px;
overflow: auto;
border: 1px solid var(--border);
border-radius: 12px;
background: #151827;
box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
}

.results-list.visible {
display: block;
}

.location-option {
width: 100%;
min-height: auto;
padding: 12px;
color: var(--text);
text-align: left;
border-radius: 0;
border-bottom: 1px solid var(--border);
background: transparent;
}

.location-option:last-child {
border-bottom: 0;
}

.location-option:hover {
background: var(--surface-2);
}

.coordinates {
display: grid;
grid-template-columns: repeat(2, 1fr);
gap: 10px;
}

.status {
min-height: 22px;
color: var(--muted);
font-size: 13px;
}

.status.error {
color: var(--danger);
}

.status.success {
color: var(--success);
}

.content {
min-width: 0;
}

.empty-state {
display: grid;
min-height: 600px;
place-items: center;
padding: 32px;
color: var(--muted);
text-align: center;
}

.result-content {
display: none;
gap: 24px;
}

.result-content.visible {
display: grid;
}

.chart-card {
padding: 20px;
overflow: hidden;
}

.chart-header {
display: flex;
justify-content: space-between;
gap: 16px;
align-items: flex-start;
margin-bottom: 16px;
}

.chart-header h2 {
margin: 0;
font-size: 24px;
}

.chart-header p {
margin: 6px 0 0;
color: var(--muted);
font-size: 14px;
}

.radix-container {
width: 100%;
overflow: auto;
}

#radix {
display: block;
width: min(100%, 860px);
height: auto;
margin: 0 auto;
}

.tabs {
display: flex;
gap: 8px;
padding: 8px;
overflow-x: auto;
}

.tab-button {
min-height: 42px;
color: var(--muted);
white-space: nowrap;
background: transparent;
}

.tab-button.active {
color: var(--text);
background: var(--surface-2);
}

.tab-panel {
display: none;
padding: 20px;
}

.tab-panel.active {
display: block;
}

.table-wrapper {
overflow-x: auto;
}

table {
width: 100%;
border-collapse: collapse;
}

th,
td {
padding: 12px 10px;
text-align: left;
border-bottom: 1px solid var(--border);
white-space: nowrap;
}

th {
color: var(--muted);
font-size: 12px;
text-transform: uppercase;
letter-spacing: 0.06em;
}

td {
font-size: 14px;
}

.planet-symbol,
.aspect-symbol {
display: inline-grid;
width: 28px;
height: 28px;
place-items: center;
margin-right: 7px;
border-radius: 50%;
background: var(--surface-2);
font-size: 18px;
}

.retrograde {
color: var(--danger);
font-weight: 800;
}

.angle-grid {
display: grid;
grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
gap: 12px;
}

.angle-item {
padding: 16px;
border: 1px solid var(--border);
border-radius: 14px;
background: var(--surface-2);
}

.angle-item strong {
display: block;
margin-bottom: 6px;
}

.angle-item span {
color: var(--muted);
}

@media (max-width: 900px) {
.layout {
grid-template-columns: 1fr;
}

.form-card {
position: static;
}
}

@media (max-width: 520px) {
.app {
width: min(100% - 20px, 1500px);
padding-top: 20px;
}

.field-row,
.coordinates {
grid-template-columns: 1fr;
}

.chart-header {
display: grid;
}

.form-card,
.chart-card,
.tab-panel {
padding: 16px;
}
}
</style>
</head>

<body>
<div class="app">
<header class="header">
<h1>Geburtshoroskop</h1>
<p>Planeten, Häuser, Aspekte und Radixgrafik</p>
</header>

<div class="layout">
<aside class="card form-card">
<form id="chartForm" class="form-grid">
<div class="field">
<label for="name">Name</label>
<input
id="name"
name="name"
type="text"
placeholder="Name"
>
</div>

<div class="field-row">
<div class="field">
<label for="date">Geburtsdatum</label>
<input
id="date"
name="date"
type="date"
required
>
</div>

<div class="field">
<label for="time">Geburtszeit</label>
<input
id="time"
name="time"
type="time"
step="60"
required
>
</div>
</div>

<div class="field place-wrapper">
<label for="place">Geburtsort</label>

<div class="place-row">
<input
id="place"
name="place"
type="text"
autocomplete="off"
placeholder="z. B. Seligenstadt, Deutschland"
required
>

<button
id="searchPlace"
class="secondary-button"
type="button"
>
Suchen
</button>
</div>

<div id="locationResults" class="results-list"></div>
</div>

<div class="coordinates">
<div class="field">
<label for="latitude">Breitengrad</label>
<input
id="latitude"
name="latitude"
type="number"
step="any"
min="-90"
max="90"
required
>
</div>

<div class="field">
<label for="longitude">Längengrad</label>
<input
id="longitude"
name="longitude"
type="number"
step="any"
min="-180"
max="180"
required
>
</div>
</div>

<div class="field">
<label for="timezone">Zeitzone</label>
<input
id="timezone"
name="timezone"
type="text"
placeholder="Europe/Berlin"
required
>
</div>

<div class="field">
<label for="houseSystem">Häusersystem</label>
<select id="houseSystem" name="houseSystem">
<option value="placidus">Placidus</option>
<option value="koch">Koch</option>
<option value="equal">Gleiches Haus</option>
<option value="whole_sign">Ganzzeichenhäuser</option>
<option value="regiomontanus">Regiomontanus</option>
<option value="campanus">Campanus</option>
</select>
</div>

<div id="status" class="status"></div>

<button
id="calculateButton"
class="primary-button"
type="submit"
>
Horoskop berechnen
</button>
</form>
</aside>

<main class="content">
<div id="emptyState" class="card empty-state">
<div>
Geburtsdaten eingeben und Horoskop berechnen.
</div>
</div>

<div id="resultContent" class="result-content">
<section class="card chart-card">
<div class="chart-header">
<div>
<h2 id="chartTitle">Radix</h2>
<p id="chartSubtitle"></p>
</div>

<button
id="downloadSvg"
class="secondary-button"
type="button"
>
SVG speichern
</button>
</div>

<div class="radix-container">
<svg
id="radix"
viewBox="0 0 900 900"
role="img"
aria-label="Radixgrafik"
></svg>
</div>
</section>

<section class="card">
<nav class="tabs">
<button
type="button"
class="tab-button active"
data-tab="planets"
>
Planeten
</button>

<button
type="button"
class="tab-button"
data-tab="houses"
>
Häuser
</button>

<button
type="button"
class="tab-button"
data-tab="aspects"
>
Aspekte
</button>

<button
type="button"
class="tab-button"
data-tab="angles"
>
Achsen
</button>
</nav>

<div id="planetsPanel" class="tab-panel active">
<div class="table-wrapper">
<table>
<thead>
<tr>
<th>Planet</th>
<th>Position</th>
<th>Haus</th>
<th>Bewegung</th>
</tr>
</thead>
<tbody id="planetRows"></tbody>
</table>
</div>
</div>

<div id="housesPanel" class="tab-panel">
<div class="table-wrapper">
<table>
<thead>
<tr>
<th>Haus</th>
<th>Position der Spitze</th>
</tr>
</thead>
<tbody id="houseRows"></tbody>
</table>
</div>
</div>

<div id="aspectsPanel" class="tab-panel">
<div class="table-wrapper">
<table>
<thead>
<tr>
<th>Planet</th>
<th>Aspekt</th>
<th>Planet</th>
<th>Orb</th>
</tr>
</thead>
<tbody id="aspectRows"></tbody>
</table>
</div>
</div>

<div id="anglesPanel" class="tab-panel">
<div id="angleGrid" class="angle-grid"></div>
</div>
</section>
</div>
</main>
</div>
</div>

<script>
const SVG_NS = "http://www.w3.org/2000/svg";

const form = document.getElementById("chartForm");
const placeInput = document.getElementById("place");
const latitudeInput = document.getElementById("latitude");
const longitudeInput = document.getElementById("longitude");
const timezoneInput = document.getElementById("timezone");
const locationResults = document.getElementById("locationResults");
const statusElement = document.getElementById("status");
const searchPlaceButton = document.getElementById("searchPlace");
const calculateButton = document.getElementById("calculateButton");
const emptyState = document.getElementById("emptyState");
const resultContent = document.getElementById("resultContent");
const radix = document.getElementById("radix");

let currentChart = null;

const signSymbols = [
"♈", "♉", "♊", "♋", "♌", "♍",
"♎", "♏", "♐", "♑", "♒", "♓"
 ];

const aspectStyles = {
"Konjunktion": {
stroke: "#efcb78",
dash: ""
},
"Sextil": {
stroke: "#6ee7ff",
dash: ""
},
"Quadrat": {
stroke: "#ff7188",
dash: ""
},
"Trigon": {
stroke: "#78e6ae",
dash: ""
},
"Quinkunx": {
stroke: "#b99cff",
dash: "7 7"
},
"Opposition": {
stroke: "#ff7188",
dash: "10 5"
}
};

function setStatus(message = "", type = "") {
statusElement.textContent = message;
statusElement.className = "status";

if (type) {
statusElement.classList.add(type);
}
}

async function readError(response) {
try {
const body = await response.json();
return body.detail || "Unbekannter Fehler";
} catch {
return "Unbekannter Fehler";
}
}

async function searchPlace() {
const place = placeInput.value.trim();

if (place.length < 2) {
setStatus("Bitte einen Ort eingeben.", "error");
return;
}

searchPlaceButton.disabled = true;
setStatus("Ort wird gesucht …");

try {
const response = await fetch(
/api/geocode?place=${encodeURIComponent(place)}`
);

if (!response.ok) {
throw new Error(await readError(response));
}

const data = await response.json();
renderLocationResults(data.results);
setStatus("Ort auswählen.");
} catch (error) {
setStatus(error.message, "error");
} finally {
searchPlaceButton.disabled = false;
}
}

function renderLocationResults(results) {
locationResults.innerHTML = "";

for (const location of results) {
const button = document.createElement("button");
button.type = "button";
button.className = "location-option";
button.textContent = location.display_name;

button.addEventListener("click", () => {
placeInput.value = location.display_name;
latitudeInput.value = location.latitude;
longitudeInput.value = location.longitude;
timezoneInput.value = location.timezone;
locationResults.classList.remove("visible");
setStatus("Ort und Zeitzone übernommen.", "success");
});

locationResults.appendChild(button);
}

locationResults.classList.add("visible");
}

searchPlaceButton.addEventListener("click", searchPlace);

placeInput.addEventListener("keydown", event => {
if (event.key === "Enter") {
event.preventDefault();
searchPlace();
}
});

document.addEventListener("click", event => {
if (!event.target.closest(".place-wrapper")) {
locationResults.classList.remove("visible");
}
});

form.addEventListener("submit", async event => {
event.preventDefault();

calculateButton.disabled = true;
setStatus("Horoskop wird berechnet …");

const payload = {
name: document.getElementById("name").value.trim(),
date: document.getElementById("date").value,
time: document.getElementById("time").value,
place: placeInput.value.trim(),
latitude: Number(latitudeInput.value),
longitude: Number(longitudeInput.value),
timezone: timezoneInput.value.trim(),
house_system:
document.getElementById("houseSystem").value
};

try {
const response = await fetch("/api/chart", {
method: "POST",
headers: {
"Content-Type": "application/json"
},
body: JSON.stringify(payload)
});

if (!response.ok) {
throw new Error(await readError(response));
}

currentChart = await response.json();
renderChart(currentChart);

emptyState.style.display = "none";
resultContent.classList.add("visible");
setStatus("Berechnung abgeschlossen.", "success");
} catch (error) {
setStatus(error.message, "error");
} finally {
calculateButton.disabled = false;
}
});

function renderChart(data) {
const title = data.subject.name
? Radix von${data.subject.name}`
: "Radix";

document.getElementById("chartTitle").textContent = title;

document.getElementById("chartSubtitle").textContent =
${formatDate(data.subject.date)} · + ``${data.subject.time} Uhr · +
${data.subject.place}`;

renderPlanetTable(data.planets);
renderHouseTable(data.houses);
renderAspectTable(data.aspects);
renderAngles(data.angles);
drawRadix(data);
}

function formatDate(dateString) {
const [year, month, day] = dateString.split("-");
return ``${day}.{year}`;
}

function renderPlanetTable(planets) {
const tbody = document.getElementById("planetRows");
tbody.innerHTML = "";

for (const planet of planets) {
const row = document.createElement("tr");

row.innerHTML = &lt;td&gt; &lt;span class="planet-symbol"&gt;${planet.symbol}</span>
${escapeHtml(planet.name)} &lt;/td&gt; &lt;td&gt; ${escapeHtml(planet.formatted)}
</td>
<td>${planet.house}&lt;/td&gt; &lt;td class="${planet.retrograde ? "retrograde" : ""}">
${planet.retrograde ? "Rückläufig ℞" : "Direkt"} &lt;/td&gt;;

tbody.appendChild(row);
}
}

function renderHouseTable(houses) {
const tbody = document.getElementById("houseRows");
tbody.innerHTML = "";

for (const house of houses) {
const row = document.createElement("tr");

row.innerHTML = &lt;td&gt;Haus ${house.house}</td>
<td>${escapeHtml(house.formatted)}&lt;/td&gt;;

tbody.appendChild(row);
}
}

function renderAspectTable(aspects) {
const tbody = document.getElementById("aspectRows");
tbody.innerHTML = "";

if (!aspects.length) {
const row = document.createElement("tr");
row.innerHTML = &lt;td colspan="4"&gt;Keine Aspekte innerhalb der Orben.&lt;/td&gt;;
tbody.appendChild(row);
return;
}

for (const aspect of aspects) {
const row = document.createElement("tr");

row.innerHTML = &lt;td&gt; &lt;span class="planet-symbol"&gt; ${aspect.planet1_symbol}
</span>
${escapeHtml(aspect.planet1)} &lt;/td&gt; &lt;td&gt; &lt;span class="aspect-symbol"&gt; ${aspect.symbol}
</span>
${escapeHtml(aspect.aspect)} &lt;/td&gt; &lt;td&gt; &lt;span class="planet-symbol"&gt; ${aspect.planet2_symbol}
</span>
${escapeHtml(aspect.planet2)} &lt;/td&gt; &lt;td&gt;${aspect.orb_formatted}</td>
`;

tbody.appendChild(row);
}
}

function renderAngles(angles) {
const grid = document.getElementById("angleGrid");
grid.innerHTML = "";

const items = [
angles.ascendant,
angles.descendant,
angles.medium_coeli,
angles.imum_coeli,
angles.vertex
 ];

for (const angle of items) {
const item = document.createElement("div");
item.className = "angle-item";
item.innerHTML = &lt;strong&gt;${angle.symbol} · {escapeHtml(angle.formatted)}</span>
`;
grid.appendChild(item);
}
}

function svgElement(name, attributes = {}, text = "") {
const element = document.createElementNS(SVG_NS, name);

for (const [key, value] of Object.entries(attributes)) {
element.setAttribute(key, String(value));
}

if (text) {
element.textContent = text;
}

return element;
}

function polarPoint(centerX, centerY, radius, longitude, ascendant) {
const angle =
(180 - (longitude - ascendant)) * Math.PI / 180;

return {
x: centerX + radius * Math.cos(angle),
y: centerY - radius * Math.sin(angle)
};
}

function drawRadix(data) {
radix.innerHTML = "";

const centerX = 450;
const centerY = 450;

const outerRadius = 405;
const zodiacInnerRadius = 337;
const houseInnerRadius = 272;
const planetRadius = 305;
const aspectRadius = 225;

const ascendant = data.angles.ascendant.longitude;

const background = svgElement("circle", {
cx: centerX,
cy: centerY,
r: outerRadius,
fill: "#0d0f19",
stroke: "#363b55",
"stroke-width": 2
});

radix.appendChild(background);

for (const radius of [
outerRadius,
zodiacInnerRadius,
houseInnerRadius,
aspectRadius
 ]) {
radix.appendChild(
svgElement("circle", {
cx: centerX,
cy: centerY,
r: radius,
fill: "none",
stroke: "#363b55",
"stroke-width": radius === outerRadius ? 3 : 1.4
})
);
}

drawZodiac(
centerX,
centerY,
outerRadius,
zodiacInnerRadius,
ascendant
);

drawHouses(
data.houses,
centerX,
centerY,
outerRadius,
houseInnerRadius,
ascendant
);

drawAspects(
data.planets,
data.aspects,
centerX,
centerY,
aspectRadius,
ascendant
);

drawPlanets(
data.planets,
centerX,
centerY,
planetRadius,
ascendant
);

drawMainAxes(
data.angles,
centerX,
centerY,
outerRadius,
ascendant
);

radix.appendChild(
svgElement("circle", {
cx: centerX,
cy: centerY,
r: 5,
fill: "#efcb78"
})
);
}

function drawZodiac(
centerX,
centerY,
outerRadius,
innerRadius,
ascendant
) {
for (let index = 0; index < 12; index++) {
const longitude = index * 30;

const outer = polarPoint(
centerX,
centerY,
outerRadius,
longitude,
ascendant
);

const inner = polarPoint(
centerX,
centerY,
innerRadius,
longitude,
ascendant
);

radix.appendChild(
svgElement("line", {
x1: inner.x,
y1: inner.y,
x2: outer.x,
y2: outer.y,
stroke: "#575e80",
"stroke-width": 1.5
})
);

const label = polarPoint(
centerX,
centerY,
(outerRadius + innerRadius) / 2,
longitude + 15,
ascendant
);

radix.appendChild(
svgElement(
"text",
{
x: label.x,
y: label.y,
fill: "#efcb78",
"font-size": 30,
"font-family": "serif",
"text-anchor": "middle",
"dominant-baseline": "central"
},
signSymbols[index]
)
);

for (let degree = 5; degree < 30; degree += 5) {
const tickLongitude = longitude + degree;

const tickOuter = polarPoint(
centerX,
centerY,
outerRadius,
tickLongitude,
ascendant
);

const tickInner = polarPoint(
centerX,
centerY,
degree % 10 === 0
? outerRadius - 13
: outerRadius - 8,
tickLongitude,
ascendant
);

radix.appendChild(
svgElement("line", {
x1: tickInner.x,
y1: tickInner.y,
x2: tickOuter.x,
y2: tickOuter.y,
stroke: "#555b77",
"stroke-width": 1
})
);
}
}
}

function drawHouses(
houses,
centerX,
centerY,
outerRadius,
innerRadius,
ascendant
) {
for (const house of houses) {
const start = polarPoint(
centerX,
centerY,
innerRadius,
house.longitude,
ascendant
);

const end = polarPoint(
centerX,
centerY,
outerRadius,
house.longitude,
ascendant
);

radix.appendChild(
svgElement("line", {
x1: start.x,
y1: start.y,
x2: end.x,
y2: end.y,
stroke: [1, 4, 7, 10].includes(house.house)
? "#d8dcef"
: "#6e7597",
"stroke-width": [1, 4, 7, 10].includes(house.house)
? 2.6
: 1.15
})
);

const nextHouse =
houses[house.house % houses.length];

const midpoint = circularMidpoint(
house.longitude,
nextHouse.longitude
);

const label = polarPoint(
centerX,
centerY,
innerRadius + 25,
midpoint,
ascendant
);

radix.appendChild(
svgElement(
"text",
{
x: label.x,
y: label.y,
fill: "#abb1cc",
"font-size": 16,
"font-weight": 700,
"text-anchor": "middle",
"dominant-baseline": "central"
},
String(house.house)
)
);
}
}

function circularMidpoint(start, end) {
let adjustedEnd = end;

if (adjustedEnd < start) {
adjustedEnd += 360;
}

return ((start + adjustedEnd) / 2) % 360;
}

function drawPlanets(
planets,
centerX,
centerY,
baseRadius,
ascendant
) {
const arranged = arrangePlanets(planets);

for (const planet of arranged) {
const point = polarPoint(
centerX,
centerY,
planet.radius,
planet.longitude,
ascendant
);

const anchorPoint = polarPoint(
centerX,
centerY,
273,
planet.originalLongitude,
ascendant
);

radix.appendChild(
svgElement("line", {
x1: anchorPoint.x,
y1: anchorPoint.y,
x2: point.x,
y2: point.y,
stroke: "#5e6584",
"stroke-width": 0.8,
opacity: 0.8
})
);

radix.appendChild(
svgElement("circle", {
cx: point.x,
cy: point.y,
r: 19,
fill: "#171a28",
stroke: "#787fa4",
"stroke-width": 1
})
);

radix.appendChild(
svgElement(
"text",
{
x: point.x,
y: point.y - 1,
fill: "#f4f5fa",
"font-size": 25,
"font-family": "serif",
"text-anchor": "middle",
"dominant-baseline": "central"
},
planet.symbol
)
);

if (planet.retrograde) {
radix.appendChild(
svgElement(
"text",
{
x: point.x + 17,
y: point.y - 17,
fill: "#ff7188",
"font-size": 11,
"font-weight": 800,
"text-anchor": "middle"
},
"℞"
)
);
}
}
}

function arrangePlanets(planets) {
const sorted = [...planets]
.map(planet => ({
...planet,
originalLongitude: planet.longitude,
radius: 305
}))
.sort((a, b) => a.longitude - b.longitude);

const minimumSpacing = 7;

for (let iteration = 0; iteration < 8; iteration++) {
for (let index = 0; index < sorted.length; index++) {
const current = sorted[index];
const next = sorted[(index + 1) % sorted.length];

let difference =
(next.longitude - current.longitude + 360) % 360;

if (difference < minimumSpacing) {
const shift = (minimumSpacing - difference) / 2;

current.longitude =
(current.longitude - shift + 360) % 360;

next.longitude =
(next.longitude + shift) % 360;
}
}

sorted.sort((a, b) => a.longitude - b.longitude);
}

for (let index = 0; index < sorted.length; index++) {
sorted[index].radius =
300 + (index % 2) * 28;
}

return sorted;
}

function drawAspects(
planets,
aspects,
centerX,
centerY,
radius,
ascendant
) {
const planetMap = new Map(
planets.map(planet => [planet.name, planet])
);

for (const aspect of aspects) {
const first = planetMap.get(aspect.planet1);
const second = planetMap.get(aspect.planet2);

if (!first || !second) {
continue;
}

const start = polarPoint(
centerX,
centerY,
radius,
first.longitude,
ascendant
);

const end = polarPoint(
centerX,
centerY,
radius,
second.longitude,
ascendant
);

const style =
aspectStyles[aspect.aspect] ||
{stroke: "#8d93ae", dash: ""};

const line = svgElement("line", {
x1: start.x,
y1: start.y,
x2: end.x,
y2: end.y,
stroke: style.stroke,
"stroke-width": 1.4,
opacity: Math.max(
0.3,
0.9 - aspect.orb / 12
)
});

if (style.dash) {
line.setAttribute("stroke-dasharray", style.dash);
}

radix.appendChild(line);
}
}

function drawMainAxes(
angles,
centerX,
centerY,
radius,
ascendant
) {
const axes = [
angles.ascendant,
angles.descendant,
angles.medium_coeli,
angles.imum_coeli
 ];

for (const axis of axes) {
const point = polarPoint(
centerX,
centerY,
radius + 20,
axis.longitude,
ascendant
);

radix.appendChild(
svgElement(
"text",
{
x: point.x,
y: point.y,
fill: "#ffffff",
"font-size": 16,
"font-weight": 900,
"text-anchor": "middle",
"dominant-baseline": "central",
stroke: "#080911",
"stroke-width": 5,
"paint-order": "stroke"
},
axis.symbol
)
);
}
}

document.querySelectorAll(".tab-button").forEach(button => {
button.addEventListener("click", () => {
document
.querySelectorAll(".tab-button")
.forEach(item => item.classList.remove("active"));

document
.querySelectorAll(".tab-panel")
.forEach(item => item.classList.remove("active"));

button.classList.add("active");

document
.getElementById(${button.dataset.tab}Panel`)
.classList.add("active");
});
});

document
.getElementById("downloadSvg")
.addEventListener("click", () => {
if (!currentChart) {
return;
}

const serializer = new XMLSerializer();
const source = serializer.serializeToString(radix);

const completeSvg =
<?xml version="1.0" encoding="UTF-8"?&gt;\n${source}`;

const blob = new Blob(
[completeSvg],
{type: "image/svg+xml;charset=utf-8"}
);

const url = URL.createObjectURL(blob);
const link = document.createElement("a");

const filename = currentChart.subject.name
? radix-${slugify(currentChart.subject.name)}.svg`
: "radix.svg";

link.href = url;
link.download = filename;
document.body.appendChild(link);
link.click();
link.remove();

URL.revokeObjectURL(url);
});

function slugify(value) {
return value
.toLowerCase()
.normalize("NFD")
.replace(/[\u0300-\u036f]/g, "")
.replace(/[^a-z0-9]+/g, "-")
.replace(/^-|-`$/g, "");
}

function escapeHtml(value) {
return String(value)
.replaceAll("&", "&")
.replaceAll("<", "<")
.replaceAll(">", ">")
.replaceAll('"', """)
.replaceAll("'", "'");
}
</script>
</body>
</html>
"""

if __name__ == "__main__":
import uvicorn

uvicorn.run(
"main:app",
host="0.0.0.0",
port=8000,
reload=True,
)