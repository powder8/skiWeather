#!/usr/bin/env python3
"""Fetches live forecast data and generates index.html for Sol Mountain trip.
No dependencies beyond Python 3.10+ standard library."""

import json
import os
import sys
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import escape as html_esc
from pathlib import Path
import re
import ssl

# SSL context — macOS Python often lacks certs; fall back to unverified
SSL_CTX = ssl.create_default_context()
try:
    urllib.request.urlopen("https://api.open-meteo.com", timeout=5, context=SSL_CTX)
except urllib.error.URLError as e:
    if "CERTIFICATE_VERIFY_FAILED" in str(e):
        SSL_CTX = ssl._create_unverified_context()
except Exception:
    pass

# ─── Configuration ──────────────────────────────────────────────────────────

DIR = Path(__file__).parent
CONFIG = {
    "mountain": {"lat": 51.35, "lon": -117.95, "elev": 1900, "name": "Sol Mountain (1900m)"},
    "valley": {"lat": 50.998, "lon": -118.195, "elev": 443, "name": "Revelstoke (443m)"},
    "trip_start": "2026-03-01",
    "trip_end": "2026-03-07",
    "metar_station": "CYRV",
    "ec_station": "s0000679",
}

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SHORT_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

WMO = {
    0: ("Clear sky", "\u2600\uFE0F"), 1: ("Mainly clear", "\U0001f324\uFE0F"),
    2: ("Partly cloudy", "\u26C5"), 3: ("Overcast", "\u2601\uFE0F"),
    45: ("Fog", "\U0001f32B\uFE0F"), 48: ("Rime fog", "\U0001f32B\uFE0F"),
    51: ("Light drizzle", "\U0001f327\uFE0F"), 53: ("Drizzle", "\U0001f327\uFE0F"),
    55: ("Heavy drizzle", "\U0001f327\uFE0F"),
    56: ("Freezing drizzle", "\U0001f327\uFE0F"), 57: ("Heavy freezing drizzle", "\U0001f327\uFE0F"),
    61: ("Light rain", "\U0001f327\uFE0F"), 63: ("Rain", "\U0001f327\uFE0F"),
    65: ("Heavy rain", "\U0001f327\uFE0F"),
    66: ("Freezing rain", "\U0001f327\uFE0F"), 67: ("Heavy freezing rain", "\U0001f327\uFE0F"),
    71: ("Light snow", "\U0001f328\uFE0F"), 73: ("Snow", "\U0001f328\uFE0F"),
    75: ("Heavy snow", "\U0001f328\uFE0F"), 77: ("Snow grains", "\U0001f328\uFE0F"),
    80: ("Light showers", "\U0001f326\uFE0F"), 81: ("Showers", "\U0001f327\uFE0F"),
    82: ("Heavy showers", "\U0001f327\uFE0F"),
    85: ("Light snow showers", "\U0001f328\uFE0F"), 86: ("Heavy snow showers", "\U0001f328\uFE0F"),
    95: ("Thunderstorm", "\u26C8\uFE0F"), 96: ("T-storm + hail", "\u26C8\uFE0F"),
    99: ("Severe t-storm", "\u26C8\uFE0F"),
}


# ─── Utilities ──────────────────────────────────────────────────────────────

def deg_to_compass(deg):
    if deg is None:
        return "--"
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(deg % 360 / 45) % 8]


def wmo_info(code):
    desc, icon = WMO.get(code, WMO[3])
    return desc, icon


def freezing_level(temp_c, elev_m):
    return round(elev_m + (temp_c / 6.5) * 1000)


def fmt_date(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{SHORT_DAYS[d.weekday()]}, {MONTHS[d.month - 1]} {d.day}"


def day_of_week(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return DAY_NAMES[d.weekday()]


def trip_dates():
    start = datetime.strptime(CONFIG["trip_start"], "%Y-%m-%d")
    end = datetime.strptime(CONFIG["trip_end"], "%Y-%m-%d")
    dates = []
    d = start
    while d <= end:
        dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return dates


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def fetch_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "SolMtnWeather/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return json.loads(resp.read().decode())


def fetch_text(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "SolMtnWeather/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return resp.read().decode()


# ─── API Fetchers ───────────────────────────────────────────────────────────

def fetch_open_meteo(loc):
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={loc['lat']}&longitude={loc['lon']}"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum,"
        f"windspeed_10m_max,winddirection_10m_dominant,weathercode"
        f"&hourly=temperature_2m,snowfall,windspeed_10m,winddirection_10m,weathercode,cloudcover"
        f"&elevation={loc['elev']}"
        f"&timezone=America%2FVancouver&forecast_days=16"
    )
    print(f"  Fetching Open-Meteo for {loc['name']}...")
    return fetch_json(url)


def fetch_metar():
    url = f"https://aviationweather.gov/api/data/metar?ids={CONFIG['metar_station']}&format=json"
    print("  Fetching CYRV METAR...")
    data = fetch_json(url)
    return data[0] if data else None


def fetch_avalanche_canada():
    print("  Fetching Avalanche Canada...")
    metadata = fetch_json("https://avcan-services-api.prod.avalanche.ca/forecasts/en/metadata")

    # Find region for Sol Mountain / North Monashee
    region = None
    for r in metadata:
        title = (r.get("product", {}).get("title", "") or "").lower()
        if "monashee" in title or "north columbia" in title:
            region = r
            break

    if not region:
        # Closest by centroid
        best_dist = float("inf")
        for r in metadata:
            c = r.get("centroid")
            if not c:
                continue
            dist = abs(c["latitude"] - CONFIG["mountain"]["lat"]) + abs(c["longitude"] - CONFIG["mountain"]["lon"])
            if dist < best_dist:
                best_dist = dist
                region = r

    if not region:
        return {"region": None, "product": None}

    title = region.get("product", {}).get("title") or region.get("area", {}).get("name") or "?"
    print(f"  Found region: {title}")

    slug = region.get("product", {}).get("slug")
    if not slug:
        return {"region": region, "product": None}

    product = fetch_json(f"https://avcan-services-api.prod.avalanche.ca/forecasts/en/products/{slug}")
    return {"region": region, "product": product}


def fetch_environment_canada():
    print("  Fetching Environment Canada...")
    now = datetime.now(timezone.utc)
    for offset in range(6):
        h = (now.hour - offset) % 24
        hh = f"{h:02d}"
        dir_url = f"https://dd.weather.gc.ca/today/citypage_weather/BC/{hh}/"
        try:
            html = fetch_text(dir_url, timeout=5)
            m = re.search(r'href="([^"]*s0000679_en\.xml)"', html)
            if not m:
                continue
            xml_text = fetch_text(dir_url + m.group(1), timeout=5)
            return parse_ec_xml(xml_text)
        except Exception:
            continue
    raise RuntimeError("Environment Canada data unavailable")


def parse_ec_xml(xml_text):
    forecasts = []
    for m in re.finditer(r"<forecast>(.*?)</forecast>", xml_text, re.DOTALL):
        block = m.group(1)
        period_m = re.search(r'textForecastName="([^"]*)"', block)
        summary_m = re.search(r"<textSummary>([^<]*)</textSummary>", block)
        temp_m = re.search(r"<temperature[^>]*>(-?\d+)</temperature>", block)
        temp_class_m = re.search(r'<temperature[^>]*class="([^"]*)"', block)
        if summary_m:
            forecasts.append({
                "period": period_m.group(1) if period_m else "",
                "summary": summary_m.group(1),
                "temp": int(temp_m.group(1)) if temp_m else None,
                "temp_class": temp_class_m.group(1) if temp_class_m else None,
            })
    return forecasts


# ─── Data Processing ────────────────────────────────────────────────────────

def extract_hourly_period(hourly, date_str, start_h, end_h):
    temps, snows, winds, wind_dirs, codes, clouds = [], [], [], [], [], []
    for i, t in enumerate(hourly["time"]):
        if not t.startswith(date_str):
            continue
        hour = int(t.split("T")[1].split(":")[0])
        if start_h <= hour < end_h:
            temps.append(hourly["temperature_2m"][i])
            snows.append(hourly["snowfall"][i] or 0)
            winds.append(hourly["windspeed_10m"][i] or 0)
            wind_dirs.append(hourly["winddirection_10m"][i])
            codes.append(hourly["weathercode"][i])
            clouds.append(hourly["cloudcover"][i] or 0)

    if not temps:
        return None

    max_wind_idx = winds.index(max(winds))
    return {
        "temp_min": round(min(temps)),
        "temp_max": round(max(temps)),
        "temp_avg": round(sum(temps) / len(temps)),
        "snow_total": round(sum(snows), 1),
        "wind_max": round(max(winds)),
        "wind_dir": deg_to_compass(wind_dirs[max_wind_idx]),
        "weather_code": sorted(codes, reverse=True)[0],
        "cloud_avg": round(sum(clouds) / len(clouds)),
    }


def process_day(date_str, mtn_data, val_data):
    try:
        day_idx = mtn_data["daily"]["time"].index(date_str)
    except ValueError:
        return None

    d = mtn_data["daily"]
    mtn = {
        "high": round(d["temperature_2m_max"][day_idx]),
        "low": round(d["temperature_2m_min"][day_idx]),
        "precip": d["precipitation_sum"][day_idx],
        "snow": round(d["snowfall_sum"][day_idx], 1),
        "wind_max": round(d["windspeed_10m_max"][day_idx]),
        "wind_dir": deg_to_compass(d["winddirection_10m_dominant"][day_idx]),
        "weather_code": d["weathercode"][day_idx],
    }

    val = None
    try:
        vi = val_data["daily"]["time"].index(date_str)
        vd = val_data["daily"]
        val = {
            "high": round(vd["temperature_2m_max"][vi]),
            "low": round(vd["temperature_2m_min"][vi]),
            "snow": round(vd["snowfall_sum"][vi], 1),
            "weather_code": vd["weathercode"][vi],
        }
    except (ValueError, KeyError):
        pass

    am = extract_hourly_period(mtn_data["hourly"], date_str, 6, 12)
    pm = extract_hourly_period(mtn_data["hourly"], date_str, 12, 18)
    night = extract_hourly_period(mtn_data["hourly"], date_str, 18, 24)
    all_day = extract_hourly_period(mtn_data["hourly"], date_str, 6, 24)
    avg_cloud = all_day["cloud_avg"] if all_day else 50
    fl = freezing_level(mtn["high"], CONFIG["mountain"]["elev"])

    desc, icon = wmo_info(mtn["weather_code"])
    return {
        "date": date_str,
        "date_fmt": fmt_date(date_str),
        "day_of_week": day_of_week(date_str),
        "icon": icon,
        "weather_desc": desc,
        "mountain": mtn,
        "valley": val,
        "am": am, "pm": pm, "night": night,
        "avg_cloud": avg_cloud,
        "freezing_level": fl,
    }


def gen_summary(day):
    parts = [day["weather_desc"]]
    if day["mountain"]["snow"] > 0:
        parts.append(f"{day['mountain']['snow']}cm snow")
    if day["mountain"]["wind_max"] > 20:
        parts.append(f"winds {day['mountain']['wind_max']} km/h")
    return ", ".join(parts)


def gen_backcountry(day):
    notes = []
    cloud = day["avg_cloud"]
    snow = day["mountain"]["snow"]
    wind = day["mountain"]["wind_max"]
    high = day["mountain"]["high"]

    if cloud < 30:
        notes.append("Excellent visibility for alpine objectives. Good day for bigger terrain.")
    elif cloud > 80:
        notes.append("Flat light likely in alpine. Favour treed terrain and lower-angle runs.")
    else:
        notes.append("Variable visibility through the day.")

    if snow > 15:
        notes.append(f"Heavy snowfall ({snow}cm) \u2014 deep powder potential but limited vis. Stick to familiar zones.")
    elif snow > 5:
        notes.append(f"Fresh snow ({snow}cm) for good turns in sheltered terrain.")
    elif snow > 0:
        notes.append(f"Light snow ({snow}cm). Existing surfaces refreshed.")
    else:
        notes.append("No new snow. Look for wind-sheltered aspects where soft snow remains.")

    if wind > 25:
        notes.append(f"Strong winds ({wind} km/h {day['mountain']['wind_dir']}) \u2014 significant wind effect at ridgeline.")
    elif wind > 15:
        notes.append(f"Moderate winds ({wind} km/h {day['mountain']['wind_dir']}) \u2014 some wind loading on lee features.")

    if high > 2:
        notes.append("Warm temps \u2014 watch for wet loose on steep south-facing terrain in afternoon. Start early.")

    return " ".join(notes)


def gen_avy_notes(day, avy_data):
    notes = []
    report = avy_data.get("product", {}).get("report") if avy_data else None

    if report and report.get("dangerRatings"):
        for dr in report["dangerRatings"]:
            dval = dr.get("date", {}).get("value", "")
            if dval.startswith(day["date"]):
                alp = dr["ratings"].get("alp", {}).get("rating", {}).get("display", "?")
                tln = dr["ratings"].get("tln", {}).get("rating", {}).get("display", "?")
                btl = dr["ratings"].get("btl", {}).get("rating", {}).get("display", "?")
                notes.append(f"Avalanche Canada danger: Alpine {alp}, Treeline {tln}, Below treeline {btl}.")
                break

    snow = day["mountain"]["snow"]
    wind = day["mountain"]["wind_max"]

    if snow > 10:
        notes.append("Storm slab building with significant new snow. Natural avalanches likely on steep terrain.")
    elif snow > 3:
        notes.append("New storm slab forming with fresh snow loading.")

    if wind > 15:
        notes.append(f"Wind slab likely on lee aspects with {day['mountain']['wind_dir']} winds.")

    notes.append("Persistent weak layers (Feb 13 surface hoar, Jan 28 crust) remain in the snowpack. Assess stability as you travel.")
    return " ".join(notes)


def gen_week_outlook(days):
    total_snow = sum(d["mountain"]["snow"] for d in days)
    clear_days = sum(1 for d in days if d["avg_cloud"] < 40)
    snow_days = sum(1 for d in days if d["mountain"]["snow"] > 1)
    temp_high = max(d["mountain"]["high"] for d in days)
    temp_low = min(d["mountain"]["low"] for d in days)

    parts = [f"<strong>Week outlook:</strong> {clear_days} clear day{'s' if clear_days != 1 else ''}, "
             f"{snow_days} day{'s' if snow_days != 1 else ''} with snowfall."]
    parts.append(f"Mountain temps range {temp_low} to {temp_high}\u00B0C.")
    if total_snow > 0:
        parts.append(f"Total expected snowfall: ~{round(total_snow)}cm.")

    best = [d["date_fmt"] for d in days if d["avg_cloud"] < 50 and d["mountain"]["wind_max"] < 15]
    if best:
        parts.append(f"Best days for big objectives: {', '.join(best)}.")

    return " ".join(parts)


# ─── METAR Formatting ───────────────────────────────────────────────────────

def fmt_metar(metar):
    if not metar:
        return "METAR data unavailable."
    parts = [f"CYRV ({metar.get('reportTime', '?')[:19]} UTC):"]

    clouds = metar.get("clouds", [])
    if clouds:
        parts.append(", ".join(f"{c['cover']} at {c['base']}ft" for c in clouds))
    else:
        parts.append(metar.get("cover", "CLR"))

    vis = metar.get("visib")
    if vis is not None:
        parts.append(f"vis {round(vis * 1.609, 1)}km")

    wspd = metar.get("wspd")
    if wspd is not None:
        wind_kmh = round(wspd * 1.852)
        gust = metar.get("wgst")
        gust_str = f" gusting {round(gust * 1.852)}" if gust else ""
        parts.append(f"wind {deg_to_compass(metar.get('wdir'))} {wind_kmh}{gust_str} km/h")

    alt = metar.get("altim")
    if alt is not None:
        parts.append(f"QNH {alt:.1f} hPa")

    wx = metar.get("wxString")
    if wx:
        parts.append(f"wx: {wx}")

    return " \u2014 ".join(parts)


# ─── Avalanche Formatting ───────────────────────────────────────────────────

def avy_banner(avy_data):
    product = avy_data.get("product") if avy_data else None
    report = product.get("report") if product else None
    if not report or not report.get("dangerRatings"):
        return {"level": "?", "label": "Check avalanche.ca", "color": "var(--text-muted)"}

    levels = {"low": 1, "moderate": 2, "considerable": 3, "high": 4, "extreme": 5}
    colors = {
        "low": "var(--green)", "moderate": "var(--danger-moderate)",
        "considerable": "var(--danger-considerable)",
        "high": "var(--danger-high)", "extreme": "var(--danger-high)",
    }

    today = report["dangerRatings"][0].get("ratings", {})
    max_level, max_name = 0, "low"
    for elev in ("alp", "tln", "btl"):
        val = today.get(elev, {}).get("rating", {}).get("value", "")
        if levels.get(val, 0) > max_level:
            max_level = levels[val]
            max_name = val

    display = today.get("alp", {}).get("rating", {}).get("display") or f"{max_level} - {max_name.title()}"
    return {"level": max_level, "label": display, "color": colors.get(max_name, "var(--text-muted)")}


# ─── EC matching ────────────────────────────────────────────────────────────

def match_ec(ec_forecasts, date_str):
    if not ec_forecasts:
        return None
    d = datetime.strptime(date_str, "%Y-%m-%d")
    day_name = DAY_NAMES[d.weekday()].lower()
    matches = [f["summary"] for f in ec_forecasts if day_name in f["period"].lower()]
    return " ".join(matches) if matches else None


# ─── HTML Generation ────────────────────────────────────────────────────────

def period_to_json(p):
    if not p:
        return None
    desc, _ = wmo_info(p["weather_code"])
    return {
        "temp": f"{p['temp_avg']}\u00B0C",
        "wind": f"{p['wind_max']} km/h {p['wind_dir']}",
        "snow": f"{p['snow_total']}cm",
        "sky": desc,
    }


def generate_html(days, metar, avy_data, ec_forecasts):
    banner = avy_banner(avy_data)
    outlook = gen_week_outlook(days)
    metar_str = fmt_metar(metar)
    now_str = datetime.now().strftime("%B %d, %Y at %H:%M")

    product = avy_data.get("product") if avy_data else None
    report = product.get("report") if product else None
    region_name = ""
    if product:
        region_name = report.get("title", "") if report else ""
    if not region_name and avy_data and avy_data.get("region"):
        region_name = avy_data["region"].get("product", {}).get("title", "")
    region_name = region_name or "North Columbia"

    forecast_url = ""
    if product:
        forecast_url = product.get("url", "")
    if not forecast_url and avy_data and avy_data.get("region"):
        forecast_url = avy_data["region"].get("url", "")
    forecast_url = forecast_url or "https://www.avalanche.ca/en/forecasts"

    # Build cards JSON
    cards = []
    for i, d in enumerate(days):
        ec_text = match_ec(ec_forecasts, d["date"])
        val = d["valley"]
        if not ec_text:
            if val:
                vdesc, _ = wmo_info(val["weather_code"])
                ec_text = f"Valley: {val['high']}/{val['low']}\u00B0C, {vdesc}"
            else:
                ec_text = "No data"

        cards.append({
            "date": d["date_fmt"],
            "dayOfWeek": d["day_of_week"],
            "icon": d["icon"],
            "mtHigh": str(d["mountain"]["high"]),
            "mtLow": str(d["mountain"]["low"]),
            "valHigh": str(val["high"]) if val else "--",
            "valLow": str(val["low"]) if val else "--",
            "snow": f"{d['mountain']['snow']}cm" if d["mountain"]["snow"] > 0 else "None",
            "wind": "Calm" if d["mountain"]["wind_max"] < 5 else f"{d['mountain']['wind_max']} km/h {d['mountain']['wind_dir']}",
            "summary": gen_summary(d),
            "freezing": f"{d['freezing_level']}m",
            "am": period_to_json(d["am"]),
            "pm": period_to_json(d["pm"]),
            "night": period_to_json(d["night"]),
            "valley": ec_text,
            "metar": metar_str if i == 0 else "METAR is a live observation \u2014 check on the day.",
            "backcountry": gen_backcountry(d),
            "avyNote": gen_avy_notes(d, avy_data),
        })

    cards_json = json.dumps(cards, ensure_ascii=False)

    # Avalanche detail section
    avy_html = ""
    if report:
        avy_html = f'\n    <div class="snowpack-section">\n      <h2>Avalanche Forecast \u2014 {html_esc(region_name)}</h2>'

        if report.get("dangerRatings"):
            avy_html += '\n      <div class="snowpack-grid">'
            for dr in report["dangerRatings"]:
                dlabel = dr.get("date", {}).get("display") or dr.get("date", {}).get("value", "?")[:10]
                alp = dr.get("ratings", {}).get("alp", {}).get("rating", {}).get("display", "?")
                tln = dr.get("ratings", {}).get("tln", {}).get("rating", {}).get("display", "?")
                btl = dr.get("ratings", {}).get("btl", {}).get("rating", {}).get("display", "?")
                avy_html += (f'\n        <div class="snowpack-item">'
                             f'<div class="sp-label">{html_esc(dlabel)}</div>'
                             f'<div class="sp-value" style="font-size:0.85rem">'
                             f'Alp: {html_esc(alp)}<br>TL: {html_esc(tln)}<br>BTL: {html_esc(btl)}'
                             f'</div></div>')
            avy_html += '\n      </div>'

        for s in report.get("summaries", []):
            stype = s.get("type", {}).get("display") or s.get("type", {}).get("value", "Summary")
            content = strip_html(s.get("content", ""))
            avy_html += (f'\n      <div style="margin-top:0.75rem">'
                         f'<h3 style="font-size:0.82rem;font-weight:600;text-transform:uppercase;'
                         f'letter-spacing:0.05em;color:var(--accent);margin-bottom:0.4rem">{html_esc(stype)}</h3>'
                         f'<div class="snowpack-text">{html_esc(content)}</div></div>')

        problems = report.get("problems", [])
        if problems:
            avy_html += ('\n      <div style="margin-top:0.75rem">'
                         '<h3 style="font-size:0.82rem;font-weight:600;text-transform:uppercase;'
                         'letter-spacing:0.05em;color:var(--accent);margin-bottom:0.4rem">Avalanche Problems</h3>')
            for p in problems:
                ptype = p.get("type", {}).get("display") or p.get("type", {}).get("value", "Problem")
                comment = strip_html(p.get("comment", ""))
                raw_elevs = p.get("data", {}).get("elevations", [])
                elevs = ", ".join(e.get("display", str(e)) if isinstance(e, dict) else str(e) for e in raw_elevs)
                raw_aspects = p.get("data", {}).get("aspects", [])
                aspects = ", ".join(a.get("display", str(a)) if isinstance(a, dict) else str(a) for a in raw_aspects)
                likelihood = p.get("data", {}).get("likelihood", {}).get("display", "?")
                sz = p.get("data", {}).get("expectedSize", {})
                size = f"{sz.get('min','?')}-{sz.get('max','?')}" if sz else "?"
                avy_html += (f'\n        <div class="avy-note" style="margin-bottom:0.5rem">'
                             f'<strong>{html_esc(ptype)}</strong> \u2014 '
                             f'Likelihood: {html_esc(likelihood)}, Size: {html_esc(size)}<br>'
                             f'Elevations: {html_esc(elevs)} | Aspects: {html_esc(aspects)}<br>'
                             f'{html_esc(comment)}</div>')
            avy_html += '\n      </div>'

        advice = report.get("terrainAndTravelAdvice", [])
        if advice:
            avy_html += ('\n      <div style="margin-top:0.75rem">'
                         '<h3 style="font-size:0.82rem;font-weight:600;text-transform:uppercase;'
                         'letter-spacing:0.05em;color:var(--accent);margin-bottom:0.4rem">Travel Advice</h3>'
                         '<ul class="snowpack-text">')
            for a in advice:
                avy_html += f'\n        <li>{html_esc(a)}</li>'
            avy_html += '\n      </ul></div>'

        avy_html += '\n    </div>'

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sol Mountain Backcountry Ski Trip \u2014 March 1\u20137, 2026</title>
<style>
  :root {{
    --bg: #0f1724; --card-bg: #1a2332; --card-hover: #1f2b3d;
    --accent: #4fa3d1; --accent-light: #7ec4e8;
    --text: #e2e8f0; --text-muted: #8899aa;
    --danger-high: #e53e3e; --danger-considerable: #ed8936; --danger-moderate: #ecc94b;
    --snow: #b8d4e8; --border: #2d3a4d; --green: #48bb78;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6; min-height: 100vh;
  }}
  .container {{ max-width: 900px; margin: 0 auto; padding: 1.5rem 1rem; }}
  header {{ text-align: center; margin-bottom: 1.5rem; padding-bottom: 1.5rem; border-bottom: 1px solid var(--border); }}
  header h1 {{ font-size: 1.75rem; font-weight: 700; color: #fff; margin-bottom: 0.25rem; }}
  .dates {{ font-size: 1.1rem; color: var(--accent-light); font-weight: 500; }}
  .location-info {{ color: var(--text-muted); font-size: 0.9rem; margin-top: 0.5rem; line-height: 1.5; }}
  .avy-banner {{
    display: inline-flex; align-items: center; gap: 0.5rem;
    margin-top: 1rem; padding: 0.6rem 1.2rem;
    border-radius: 8px; font-size: 0.9rem; font-weight: 600;
  }}
  .avy-banner a {{ text-decoration: underline; text-underline-offset: 2px; }}
  .avy-banner a:hover {{ color: #fff; }}
  .avy-dot {{ width: 10px; height: 10px; border-radius: 50%; animation: pulse 2s infinite; }}
  @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}
  .trip-overview {{
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px;
    padding: 1rem 1.25rem; margin-bottom: 1.5rem; font-size: 0.88rem;
    color: var(--text-muted); line-height: 1.7;
  }}
  .trip-overview strong {{ color: var(--text); }}
  .day-card {{
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px;
    margin-bottom: 0.75rem; overflow: hidden; transition: border-color 0.2s; cursor: pointer;
  }}
  .day-card:hover {{ border-color: var(--accent); }}
  .day-card.expanded {{ border-color: var(--accent); }}
  .day-summary {{
    display: grid; grid-template-columns: 7.5rem 3rem 1fr auto;
    align-items: center; gap: 0.75rem; padding: 0.9rem 1.25rem; user-select: none;
  }}
  .day-date {{ font-weight: 600; font-size: 0.95rem; color: #fff; line-height: 1.3; }}
  .day-date small {{ display: block; font-weight: 400; font-size: 0.78rem; color: var(--text-muted); }}
  .weather-icon {{ font-size: 1.5rem; text-align: center; line-height: 1; }}
  .day-info {{ display: flex; flex-wrap: wrap; gap: 0.5rem 1.5rem; font-size: 0.85rem; }}
  .day-info .info-item {{ display: flex; align-items: center; gap: 0.3rem; }}
  .info-label {{ color: var(--text-muted); font-size: 0.78rem; }}
  .info-value {{ font-weight: 500; }}
  .info-value.snow-value {{ color: var(--snow); }}
  .info-value.temp-value {{ color: var(--accent-light); }}
  .day-oneliner {{ font-size: 0.82rem; color: var(--text-muted); text-align: right; min-width: 0; white-space: nowrap; }}
  .expand-arrow {{ color: var(--text-muted); font-size: 0.7rem; transition: transform 0.2s; margin-left: 0.5rem; flex-shrink: 0; }}
  .day-card.expanded .expand-arrow {{ transform: rotate(180deg); }}
  .day-detail {{ display: none; padding: 0 1.25rem 1.25rem; border-top: 1px solid var(--border); }}
  .day-card.expanded .day-detail {{ display: block; }}
  .detail-section {{ margin-top: 1rem; }}
  .detail-section h3 {{
    font-size: 0.82rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--accent); margin-bottom: 0.5rem; padding-bottom: 0.3rem; border-bottom: 1px solid var(--border);
  }}
  .detail-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.5rem; }}
  .detail-cell {{ background: rgba(0,0,0,0.2); border-radius: 6px; padding: 0.6rem 0.75rem; font-size: 0.82rem; }}
  .detail-cell .cell-label {{ font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 0.25rem; }}
  .detail-cell .cell-value {{ font-weight: 500; color: var(--text); line-height: 1.4; }}
  .detail-text {{ font-size: 0.85rem; color: var(--text); line-height: 1.6; }}
  .detail-text p {{ margin-bottom: 0.4rem; }}
  .backcountry-note {{ background: rgba(72,187,120,0.08); border-left: 3px solid var(--green); border-radius: 0 6px 6px 0; padding: 0.6rem 0.9rem; font-size: 0.84rem; line-height: 1.6; }}
  .avy-note {{ background: rgba(237,137,54,0.08); border-left: 3px solid var(--danger-considerable); border-radius: 0 6px 6px 0; padding: 0.6rem 0.9rem; font-size: 0.84rem; line-height: 1.6; }}
  .snowpack-section {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; padding: 1.25rem; margin-top: 1.5rem; }}
  .snowpack-section h2 {{ font-size: 1rem; font-weight: 600; margin-bottom: 0.75rem; color: #fff; }}
  .snowpack-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0.75rem; margin-bottom: 1rem; }}
  .snowpack-item {{ background: rgba(0,0,0,0.2); border-radius: 6px; padding: 0.75rem; }}
  .snowpack-item .sp-label {{ font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; }}
  .snowpack-item .sp-value {{ font-size: 0.95rem; font-weight: 600; margin-top: 0.2rem; }}
  .snowpack-text {{ font-size: 0.85rem; color: var(--text-muted); line-height: 1.7; }}
  .snowpack-text li {{ margin-bottom: 0.3rem; }}
  footer {{ margin-top: 1.5rem; padding-top: 1.25rem; border-top: 1px solid var(--border); }}
  footer h2 {{ font-size: 1rem; font-weight: 600; margin-bottom: 0.75rem; color: #fff; }}
  .link-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.5rem; margin-bottom: 1rem; }}
  .link-item {{
    display: block; padding: 0.6rem 0.9rem; background: var(--card-bg); border: 1px solid var(--border);
    border-radius: 8px; color: var(--accent-light); text-decoration: none; font-size: 0.85rem;
    transition: border-color 0.2s, background 0.2s;
  }}
  .link-item:hover {{ border-color: var(--accent); background: var(--card-hover); }}
  .link-item small {{ display: block; color: var(--text-muted); font-size: 0.75rem; margin-top: 0.15rem; }}
  .last-updated {{ text-align: center; font-size: 0.78rem; color: var(--text-muted); margin-top: 1rem; padding-bottom: 1rem; }}
  .auto-note {{ text-align: center; font-size: 0.75rem; color: var(--text-muted); margin-top: 0.5rem; font-style: italic; }}
  @media (max-width: 640px) {{
    .container {{ padding: 1rem 0.75rem; }}
    header h1 {{ font-size: 1.35rem; }}
    .day-summary {{ grid-template-columns: 1fr; gap: 0.4rem; padding: 0.75rem 1rem; position: relative; }}
    .day-date {{ display: flex; align-items: center; gap: 0.75rem; }}
    .day-date small {{ display: inline; }}
    .weather-icon {{ position: absolute; right: 1rem; font-size: 1.3rem; }}
    .day-oneliner {{ text-align: left; white-space: normal; }}
    .detail-grid {{ grid-template-columns: 1fr; }}
    .link-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Sol Mountain Backcountry Ski Trip</h1>
    <div class="dates">March 1 \\u2013 7, 2026</div>
    <div class="location-info">
      Monashee Mountains, ~50km north of Revelstoke, BC<br>
      Lodge at ~1900m \\u00B7 Skiing to ~2500m
    </div>
    <div class="avy-banner" style="border: 1px solid {banner['color']}40; background: {banner['color']}15; color: {banner['color']};">
      <span class="avy-dot" style="background: {banner['color']}"></span>
      Avalanche Danger: {html_esc(banner['label'])} &nbsp;
      <a href="{html_esc(forecast_url)}" target="_blank" rel="noopener" style="color: {banner['color']}">Details</a>
    </div>
  </header>

  <div class="trip-overview">{outlook}</div>

  <div id="cards"></div>

  {avy_html}

  <footer>
    <h2>Live Data Sources</h2>
    <div class="link-grid">
      <a class="link-item" href="{html_esc(forecast_url)}" target="_blank" rel="noopener">
        Avalanche Canada \\u2014 {html_esc(region_name)}
        <small>Daily danger ratings &amp; snowpack analysis</small>
      </a>
      <a class="link-item" href="https://www.snow-forecast.com/resorts/Sol-Mountain-Touring/6day/mid" target="_blank" rel="noopener">
        Snow-Forecast \\u2014 Sol Mountain
        <small>6-day mountain forecast</small>
      </a>
      <a class="link-item" href="https://weather.gc.ca/city/pages/bc-65_metric_e.html" target="_blank" rel="noopener">
        Environment Canada \\u2014 Revelstoke
        <small>Official valley forecast</small>
      </a>
      <a class="link-item" href="https://aviationweather.gov/api/data/metar?ids=CYRV&format=decoded" target="_blank" rel="noopener">
        CYRV Aviation METAR
        <small>Revelstoke airport obs</small>
      </a>
      <a class="link-item" href="https://solmountain.com/conditions/" target="_blank" rel="noopener">
        Sol Mountain Lodge \\u2014 Conditions
        <small>Current snowpack &amp; terrain report</small>
      </a>
      <a class="link-item" href="https://open-meteo.com/" target="_blank" rel="noopener">
        Open-Meteo API
        <small>Mountain &amp; valley forecast data source</small>
      </a>
    </div>
    <div class="last-updated">Last updated: {html_esc(now_str)}</div>
    <div class="auto-note">Auto-generated from live APIs. Always verify with primary sources before making terrain decisions.</div>
  </footer>
</div>

<script>
const days = {cards_json};

function renderCards() {{
  var c = document.getElementById("cards");
  c.innerHTML = days.map(function(d, i) {{
    function pc(label, p) {{
      if (!p) return '<div class="detail-cell"><div class="cell-label">'+label+'</div><div class="cell-value">No data</div></div>';
      return '<div class="detail-cell"><div class="cell-label">'+label+'</div><div class="cell-value">'
        +p.sky+'<br>'+p.temp+', Wind '+p.wind+'<br>Snow: '+p.snow+'</div></div>';
    }}
    return '<div class="day-card" onclick="toggle(this)">'
      +'<div class="day-summary">'
      +'<div class="day-date">'+d.date+'<small>'+d.dayOfWeek+'</small></div>'
      +'<div class="weather-icon">'+d.icon+'</div>'
      +'<div class="day-info">'
      +'<div class="info-item"><span class="info-label">Mtn</span><span class="info-value temp-value">'+d.mtLow+' / '+d.mtHigh+'\\u00B0C</span></div>'
      +'<div class="info-item"><span class="info-label">Valley</span><span class="info-value">'+d.valLow+' / '+d.valHigh+'\\u00B0C</span></div>'
      +'<div class="info-item"><span class="info-label">Snow</span><span class="info-value snow-value">'+d.snow+'</span></div>'
      +'<div class="info-item"><span class="info-label">Wind</span><span class="info-value">'+d.wind+'</span></div>'
      +'</div>'
      +'<div class="day-oneliner">'+d.summary+'<span class="expand-arrow">\\u25BC</span></div>'
      +'</div>'
      +'<div class="day-detail">'
      +'<div class="detail-section"><h3>Mountain Forecast (1900m)</h3>'
      +'<div class="detail-grid">'+pc('Morning',d.am)+pc('Afternoon',d.pm)+pc('Night',d.night)+'</div>'
      +'<div style="margin-top:0.4rem;font-size:0.82rem;color:var(--text-muted)">Freezing level: '+d.freezing+'</div></div>'
      +'<div class="detail-section"><h3>Valley Forecast (Revelstoke)</h3><div class="detail-text"><p>'+d.valley+'</p></div></div>'
      +'<div class="detail-section"><h3>Aviation Weather (CYRV)</h3><div class="detail-text"><p>'+d.metar+'</p></div></div>'
      +'<div class="detail-section"><h3>Backcountry Notes</h3><div class="backcountry-note">'+d.backcountry+'</div></div>'
      +'<div class="detail-section"><h3>Avalanche Considerations</h3><div class="avy-note">'+d.avyNote+'</div></div>'
      +'</div></div>';
  }}).join("");
}}
function toggle(card) {{ card.classList.toggle("expanded"); }}
renderCards();
</script>
</body>
</html>'''


# ─── Data Persistence ───────────────────────────────────────────────────────

def load_previous():
    try:
        with open(CONFIG["dataFile"], "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"days": {}}


def save_data(data):
    with open(CONFIG["dataFile"], "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ─── Main ───────────────────────────────────────────────────────────────────

def safe_fetch(name, fn):
    try:
        result = fn()
        print(f"  \u2713 {name}")
        return result
    except Exception as e:
        print(f"  \u2717 {name}: {e}")
        return None


def main():
    print("Sol Mountain Ski Weather \u2014 Build\n")
    print("Fetching live data...")

    mtn_data = safe_fetch("Open-Meteo (mountain)", lambda: fetch_open_meteo(CONFIG["mountain"]))
    val_data = safe_fetch("Open-Meteo (valley)", lambda: fetch_open_meteo(CONFIG["valley"]))
    metar = safe_fetch("CYRV METAR", fetch_metar)
    avy_data = safe_fetch("Avalanche Canada", fetch_avalanche_canada)
    ec_forecasts = safe_fetch("Environment Canada", fetch_environment_canada)

    if not mtn_data:
        print("\nFATAL: Open-Meteo mountain data is required. Exiting.")
        sys.exit(1)

    if not val_data:
        val_data = mtn_data  # fallback

    dates = trip_dates()
    previous = load_previous()
    days = []

    print(f"\nProcessing {len(dates)} trip dates...")
    for date_str in dates:
        day = process_day(date_str, mtn_data, val_data)
        if day:
            days.append(day)
            previous["days"][date_str] = day
        elif date_str in previous.get("days", {}):
            print(f"  Using cached data for {date_str}")
            days.append(previous["days"][date_str])
        else:
            print(f"  No data available for {date_str}")

    if not days:
        print("\nNo forecast data available. Exiting.")
        sys.exit(1)

    previous["lastUpdated"] = datetime.now(timezone.utc).isoformat()
    previous["metar"] = metar
    save_data(previous)

    print("\nGenerating index.html...")
    html = generate_html(days, metar, avy_data, ec_forecasts)
    out = CONFIG.get("outFile", DIR / "index.html")
    with open(out, "w") as f:
        f.write(html)

    kb = len(html) / 1024
    print(f"\u2713 Written to {out} ({kb:.1f} KB)")
    print(f"\u2713 Data cached to {CONFIG['dataFile']}")
    print("\nDone!")


CONFIG["dataFile"] = str(DIR / "data.json")
CONFIG["outFile"] = str(DIR / "index.html")

if __name__ == "__main__":
    main()
