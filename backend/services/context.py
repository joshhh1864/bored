import asyncio
import httpx
from datetime import datetime


# ─── Config ────────────────────────────────────────────────────────────────────
WEATHER_API_KEY = "your_openweathermap_key"
NEWS_API_KEY    = "your_newsapi_key"
CITY            = "Kuala Lumpur"  # or make this dynamic per user


# ─── Individual Fetchers ────────────────────────────────────────────────────────

def get_time_context() -> dict:
    """No API needed — derives meaning from current time and day."""
    now  = datetime.now()
    hour = now.hour

    if 5 <= hour < 12:
        time_of_day = "morning"
    elif 12 <= hour < 17:
        time_of_day = "afternoon"
    elif 17 <= hour < 21:
        time_of_day = "evening"
    else:
        time_of_day = "night"

    return {
        "day":         now.strftime("%A"),           # e.g. "Monday"
        "date":        now.strftime("%B %d, %Y"),    # e.g. "June 22, 2025"
        "time":        now.strftime("%I:%M %p"),     # e.g. "09:14 AM"
        "time_of_day": time_of_day,                  # e.g. "morning"
        "is_weekend":  now.weekday() >= 5,           # True on Sat/Sun
    }


async def get_weather_context(client: httpx.AsyncClient) -> dict:
    """Fetches current weather from OpenWeatherMap."""
    try:
        response = await client.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={
                "q":     CITY,
                "appid": WEATHER_API_KEY,
                "units": "metric",
            },
            timeout=5.0,
        )
        data = response.json()
        return {
            "city":        data["name"],
            "condition":   data["weather"][0]["description"],  # e.g. "light rain"
            "temperature": data["main"]["temp"],               # e.g. 28.4
            "humidity":    data["main"]["humidity"],           # e.g. 80
            "feels_like":  data["main"]["feels_like"],
        }
    except Exception as e:
        print(f"[Weather] Failed: {e}")
        return {}


async def get_news_context(client: httpx.AsyncClient) -> dict:
    """Fetches top headlines from NewsAPI."""
    try:
        response = await client.get(
            "https://newsapi.org/v2/top-headlines",
            params={
                "country":  "my",       # Malaysia — change as needed
                "pageSize": 5,
                "apiKey":   NEWS_API_KEY,
            },
            timeout=5.0,
        )
        articles = response.json().get("articles", [])
        headlines = [a["title"] for a in articles if a.get("title")]
        return {"headlines": headlines}
    except Exception as e:
        print(f"[News] Failed: {e}")
        return {"headlines": []}


# ─── Main Gatherer ──────────────────────────────────────────────────────────────

async def gather_context() -> dict:
    """
    Fires all context fetchers in parallel and returns a single merged dict.
    This is what Layer 2 (Claude) will receive.
    """
    async with httpx.AsyncClient() as client:
        time_ctx, weather_ctx, news_ctx = await asyncio.gather(
            asyncio.to_thread(get_time_context),   # sync fn, run in thread
            get_weather_context(client),
            get_news_context(client),
        )

    return {
        "time":    time_ctx,
        "weather": weather_ctx,
        "news":    news_ctx,
    }


# ─── Quick Test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    context = asyncio.run(gather_context())

    print("\n=== CONTEXT SNAPSHOT ===")
    print(f"  Day        : {context['time']['day']}, {context['time']['time_of_day']}")
    print(f"  Is weekend : {context['time']['is_weekend']}")
    print(f"  Weather    : {context['weather'].get('condition')}, {context['weather'].get('temperature')}°C")
    print(f"  Headlines  : {context['news']['headlines'][:2]}")