import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx


# ─── Config ────────────────────────────────────────────────────────────────────
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "7725d62ed0c01f3e847e469cff245076")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "pub_30716dc2759d42c4b6edc2c10eb81f9c")

CITY = os.getenv("CITY", "Kuala Lumpur")
COUNTRY_CODE = os.getenv("COUNTRY_CODE", "my")  # ISO 3166-1 alpha-2
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Asia/Kuala_Lumpur"))

# Kuala Lumpur — used so weather is not resolved against a country name.
LAT = float(os.getenv("LAT", "3.1390"))
LON = float(os.getenv("LON", "101.6869"))

REQUEST_TIMEOUT = 8.0
WIKIPEDIA_USER_AGENT = "bored.ai/1.0 (https://github.com; one-word-prompter context-gatherer)"
MALAYSIA_HOLIDAYS_ICS = (
    "https://calendar.google.com/calendar/ical/"
    "en.malaysia%23holiday%40group.v.calendar.google.com/public/basic.ics"
)


# ─── Individual Fetchers ────────────────────────────────────────────────────────

def get_time_context(now: datetime | None = None) -> dict:
    """No API needed — derives meaning from current local time and day."""
    now = now or datetime.now(TIMEZONE)
    hour = now.hour
    month = now.month

    if 5 <= hour < 12:
        time_of_day = "morning"
    elif 12 <= hour < 17:
        time_of_day = "afternoon"
    elif 17 <= hour < 21:
        time_of_day = "evening"
    else:
        time_of_day = "night"

    # Peninsular Malaysia monsoon windows — useful for indoor vs outdoor hints.
    if month in (11, 12, 1, 2, 3):
        season = "northeast monsoon"
    elif month in (5, 6, 7, 8, 9):
        season = "southwest monsoon"
    else:
        season = "inter-monsoon"

    return {
        "day": now.strftime("%A"),
        "date": now.strftime("%B %d, %Y"),
        "iso_date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%I:%M %p"),
        "hour": hour,
        "month": month,
        "time_of_day": time_of_day,
        "is_weekend": now.weekday() >= 5,
        "season": season,
        "timezone": str(TIMEZONE),
    }


def get_location_context() -> dict:
    return {
        "city": CITY,
        "country_code": COUNTRY_CODE.upper(),
        "lat": LAT,
        "lon": LON,
    }


def _weather_from_openweather(data: dict) -> dict:
    weather = data.get("weather") or [{}]
    condition = weather[0].get("description", "")
    weather_id = int(weather[0].get("id") or 0)
    main = data.get("main") or {}
    temp = main.get("temp")
    rain_mm = (data.get("rain") or {}).get("1h", 0) or 0

    group = weather_id // 100
    is_stormy = group == 2
    is_rainy = group in (2, 3, 5) or rain_mm > 0
    is_hot = isinstance(temp, (int, float)) and temp >= 32
    is_humid = (main.get("humidity") or 0) >= 80

    return {
        "city": data.get("name") or CITY,
        "condition": condition,
        "condition_main": weather[0].get("main", ""),
        "weather_id": weather_id,
        "temperature": temp,
        "feels_like": main.get("feels_like"),
        "humidity": main.get("humidity"),
        "wind_speed": (data.get("wind") or {}).get("speed"),
        "cloud_cover": (data.get("clouds") or {}).get("all"),
        "rain_mm": rain_mm,
        "is_rainy": is_rainy,
        "is_stormy": is_stormy,
        "is_hot": is_hot,
        "is_humid": is_humid,
        "outdoor_friendly": not is_rainy and not is_stormy,
        "source": "openweathermap",
    }


def _wmo_to_condition(code: int) -> tuple[str, bool, bool]:
    """Map Open-Meteo WMO codes to a short condition plus rain/storm flags."""
    if code == 0:
        return "clear sky", False, False
    if code in (1, 2):
        return "partly cloudy", False, False
    if code == 3:
        return "overcast", False, False
    if code in (45, 48):
        return "fog", False, False
    if code in (51, 53, 55, 56, 57):
        return "drizzle", True, False
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "rain", True, False
    if code in (95, 96, 99):
        return "thunderstorm", True, True
    return "unknown", False, False


def _weather_from_open_meteo(data: dict) -> dict:
    current = data.get("current") or {}
    code = int(current.get("weather_code") or 0)
    condition, is_rainy, is_stormy = _wmo_to_condition(code)
    temp = current.get("temperature_2m")
    rain_mm = current.get("precipitation") or 0
    humidity = current.get("relative_humidity_2m")
    is_rainy = is_rainy or rain_mm > 0
    is_hot = isinstance(temp, (int, float)) and temp >= 32
    is_humid = (humidity or 0) >= 80

    return {
        "city": CITY,
        "condition": condition,
        "condition_main": condition.split()[0].title() if condition else "",
        "weather_id": code,
        "temperature": temp,
        "feels_like": current.get("apparent_temperature"),
        "humidity": humidity,
        "wind_speed": current.get("wind_speed_10m"),
        "cloud_cover": current.get("cloud_cover"),
        "rain_mm": rain_mm,
        "is_rainy": is_rainy,
        "is_stormy": is_stormy,
        "is_hot": is_hot,
        "is_humid": is_humid,
        "outdoor_friendly": not is_rainy and not is_stormy,
        "source": "open-meteo",
    }


async def get_weather_context(client: httpx.AsyncClient) -> dict:
    """Current weather for the configured city, with an Open-Meteo fallback."""
    try:
        response = await client.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={
                "lat": LAT,
                "lon": LON,
                "appid": WEATHER_API_KEY,
                "units": "metric",
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("weather") and data.get("main"):
            return _weather_from_openweather(data)
        raise ValueError(data.get("message") or "unexpected OpenWeatherMap payload")
    except Exception as e:
        print(f"[Weather] OpenWeatherMap failed ({e}); trying Open-Meteo")

    try:
        response = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LAT,
                "longitude": LON,
                "current": ",".join(
                    [
                        "temperature_2m",
                        "relative_humidity_2m",
                        "apparent_temperature",
                        "weather_code",
                        "precipitation",
                        "cloud_cover",
                        "wind_speed_10m",
                    ]
                ),
                "timezone": str(TIMEZONE),
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return _weather_from_open_meteo(response.json())
    except Exception as e:
        print(f"[Weather] Failed: {e}")
        return {
            "city": CITY,
            "condition": None,
            "temperature": None,
            "is_rainy": False,
            "is_stormy": False,
            "is_hot": False,
            "outdoor_friendly": True,
            "source": None,
        }


async def get_news_context(client: httpx.AsyncClient) -> dict:
    """Top local headlines from NewsData.io."""
    try:
        response = await client.get(
            "https://newsdata.io/api/1/latest",
            params={
                "apikey": NEWS_API_KEY,
                "country": COUNTRY_CODE,
                "language": "en",
                "size": 8,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        articles = payload.get("results") or []
        stories = []
        for article in articles:
            title = (article.get("title") or "").strip()
            if not title:
                continue
            description = (article.get("description") or "").strip()
            stories.append(
                {
                    "title": title,
                    "description": description[:240] if description else "",
                    "category": article.get("category") or [],
                    "source": article.get("source_id") or article.get("source_name"),
                }
            )
        headlines = [s["title"] for s in stories]
        return {"headlines": headlines, "stories": stories[:6]}
    except Exception as e:
        print(f"[News] Failed: {e}")
        return {"headlines": [], "stories": []}


def _unfold_ics(text: str) -> str:
    return text.replace("\r\n ", "").replace("\n ", "").replace("\r\n\t", "").replace("\n\t", "")


def _parse_ics_holidays(text: str) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    for block in _unfold_ics(text).split("BEGIN:VEVENT")[1:]:
        date = None
        summary = None
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if line.startswith("DTSTART"):
                value = line.split(":", 1)[-1].strip()
                if len(value) >= 8 and value[:8].isdigit():
                    date = f"{value[:4]}-{value[4:6]}-{value[6:8]}"
            elif line.startswith("SUMMARY"):
                summary = line.split(":", 1)[-1].strip()
        if date and summary:
            events.append((date, summary))
    events.sort(key=lambda item: item[0])
    return events


async def _get_public_holidays(client: httpx.AsyncClient, today: str) -> list[dict]:
    try:
        response = await client.get(MALAYSIA_HOLIDAYS_ICS, timeout=15.0)
        response.raise_for_status()
        seen: set[tuple[str, str]] = set()
        holidays = []
        for date, name in _parse_ics_holidays(response.text):
            if date < today or (date, name) in seen:
                continue
            seen.add((date, name))
            holidays.append({"name": name, "date": date, "is_today": date == today})
            if len(holidays) >= 5:
                break
        return holidays
    except Exception as e:
        print(f"[Events] Holidays failed: {e}")
        return []


async def _get_on_this_day(client: httpx.AsyncClient, now: datetime) -> list[dict]:
    month = f"{now.month:02d}"
    day = f"{now.day:02d}"
    try:
        response = await client.get(
            f"https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/selected/{month}/{day}",
            headers={"User-Agent": WIKIPEDIA_USER_AGENT, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        selected = (response.json() or {}).get("selected") or []
        events = []
        for item in selected[:4]:
            text = (item.get("text") or "").strip()
            year = item.get("year")
            if text:
                events.append({"year": year, "text": text})
        return events
    except Exception as e:
        print(f"[Events] On-this-day failed: {e}")
        return []


async def _get_local_event_headlines(client: httpx.AsyncClient) -> list[str]:
    """Uses the news API as a stand-in for 'what's on' locally (concerts, festivals, matches)."""
    try:
        response = await client.get(
            "https://newsdata.io/api/1/latest",
            params={
                "apikey": NEWS_API_KEY,
                "country": COUNTRY_CODE,
                "language": "en",
                "q": "concert OR festival OR exhibition OR match OR marathon",
                "size": 5,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        articles = (response.json() or {}).get("results") or []
        titles = []
        for article in articles:
            title = (article.get("title") or "").strip()
            if title and title not in titles:
                titles.append(title)
        return titles[:5]
    except Exception as e:
        print(f"[Events] Local listings failed: {e}")
        return []


async def get_events_context(client: httpx.AsyncClient, time_ctx: dict) -> dict:
    """Public holidays, cultural on-this-day notes, and local event-ish headlines."""
    now = datetime.now(TIMEZONE)
    today = time_ctx.get("iso_date") or now.strftime("%Y-%m-%d")

    holidays, on_this_day, local = await asyncio.gather(
        _get_public_holidays(client, today),
        _get_on_this_day(client, now),
        _get_local_event_headlines(client),
    )

    happening_today = [h["name"] for h in holidays if h.get("is_today")]
    return {
        "happening_today": happening_today,
        "upcoming_holidays": holidays,
        "on_this_day": on_this_day,
        "local_headlines": local,
    }


def get_suggestion_hints(time_ctx: dict, weather_ctx: dict, events_ctx: dict) -> dict:
    """Compact flags the suggestion layer can bias music / food / hobby picks with."""
    rainy = bool(weather_ctx.get("is_rainy") or weather_ctx.get("is_stormy"))
    hot = bool(weather_ctx.get("is_hot"))
    night = time_ctx.get("time_of_day") in ("evening", "night")
    weekend = bool(time_ctx.get("is_weekend"))
    holiday = bool(events_ctx.get("happening_today"))

    indoor_preferred = rainy or weather_ctx.get("is_stormy")
    if rainy:
        energy = "low"
        mood_tags = ["cozy", "rainy", "indoor"]
    elif night:
        energy = "low" if not weekend else "medium"
        mood_tags = ["evening", "unwind"]
    elif hot:
        energy = "medium"
        mood_tags = ["cooling", "light"]
    else:
        energy = "high" if weekend else "medium"
        mood_tags = ["bright", "outdoor"] if weather_ctx.get("outdoor_friendly") else ["casual"]

    if weekend:
        mood_tags.append("weekend")
    if holiday:
        mood_tags.append("holiday")
    if time_ctx.get("season"):
        mood_tags.append(time_ctx["season"])

    return {
        "indoor_preferred": indoor_preferred,
        "outdoor_friendly": bool(weather_ctx.get("outdoor_friendly")) and not indoor_preferred,
        "energy": energy,
        "mood_tags": mood_tags,
        "time_of_day": time_ctx.get("time_of_day"),
    }


# ─── Main Gatherer ──────────────────────────────────────────────────────────────

async def gather_context() -> dict:
    """
    Fires all context fetchers in parallel and returns a single merged dict.
    This is what Layer 2 (Claude) will receive.
    """
    time_ctx = get_time_context()
    location_ctx = get_location_context()

    async with httpx.AsyncClient() as client:
        weather_ctx, news_ctx, events_ctx = await asyncio.gather(
            get_weather_context(client),
            get_news_context(client),
            get_events_context(client, time_ctx),
        )

    hints = get_suggestion_hints(time_ctx, weather_ctx, events_ctx)

    return {
        "location": location_ctx,
        "time": time_ctx,
        "weather": weather_ctx,
        "news": news_ctx,
        "events": events_ctx,
        "hints": hints,
    }


def format_context_for_prompt(context: dict) -> str:
    """Flatten gathered context into a short block the suggestion model can read."""
    time_ctx = context.get("time") or {}
    weather = context.get("weather") or {}
    news = context.get("news") or {}
    events = context.get("events") or {}
    hints = context.get("hints") or {}
    location = context.get("location") or {}

    headlines = news.get("headlines") or []
    holiday_lines = [
        f"{h.get('name')} ({h.get('date')})"
        for h in (events.get("upcoming_holidays") or [])[:3]
    ]
    on_this_day = [item.get("text") for item in (events.get("on_this_day") or [])[:2] if item.get("text")]

    temp = weather.get("temperature")
    temp_s = f"{temp}°C" if temp is not None else "unknown"

    lines = [
        f"Location: {location.get('city')}, {location.get('country_code')}",
        f"Time: {time_ctx.get('day')} {time_ctx.get('date')} {time_ctx.get('time')} ({time_ctx.get('time_of_day')}, {'weekend' if time_ctx.get('is_weekend') else 'weekday'}, {time_ctx.get('season')})",
        f"Weather: {weather.get('condition') or 'unknown'}, {temp_s}"
        f"{' — rainy, prefer indoor' if weather.get('is_rainy') else ''}"
        f"{' — stormy' if weather.get('is_stormy') else ''}"
        f"{' — hot' if weather.get('is_hot') else ''}",
        f"Mood hints: {', '.join(hints.get('mood_tags') or [])}; energy={hints.get('energy')}",
    ]
    if headlines:
        lines.append("Headlines: " + " | ".join(headlines[:4]))
    if events.get("happening_today"):
        lines.append("Today: " + ", ".join(events["happening_today"]))
    if holiday_lines:
        lines.append("Upcoming holidays: " + "; ".join(holiday_lines))
    if events.get("local_headlines"):
        lines.append("Local happenings: " + " | ".join(events["local_headlines"][:3]))
    if on_this_day:
        lines.append("On this day: " + " | ".join(on_this_day))
    return "\n".join(lines)


# ─── Quick Test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    context = asyncio.run(gather_context())

    print("\n=== CONTEXT SNAPSHOT ===")
    print(f"  Location   : {context['location']['city']}")
    print(f"  Day        : {context['time']['day']}, {context['time']['time_of_day']}")
    print(f"  Is weekend : {context['time']['is_weekend']}")
    print(f"  Season     : {context['time']['season']}")
    print(f"  Weather    : {context['weather'].get('condition')}, {context['weather'].get('temperature')}°C")
    print(f"  Rainy      : {context['weather'].get('is_rainy')}  outdoor={context['weather'].get('outdoor_friendly')}")
    print(f"  Headlines  : {(context['news'].get('headlines') or [])[:2]}")
    print(f"  Today      : {context['events'].get('happening_today')}")
    print(f"  Holidays   : {context['events'].get('upcoming_holidays')}")
    print(f"  Local      : {context['events'].get('local_headlines')[:2]}")
    print(f"  Hints      : {context['hints']}")
    print("\n=== PROMPT BLOCK ===")
    print(format_context_for_prompt(context))
