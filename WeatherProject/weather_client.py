"""Всё, что связано с интернет-сервисом Open-Meteo: погода и поиск городов.

Open-Meteo бесплатный и не требует регистрации или ключа.
"""
from datetime import datetime, timezone

import httpx

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

# Какие показатели просим: температура, влажность, скорость ветра.
FIELDS = "temperature_2m,relative_humidity_2m,wind_speed_10m"


async def fetch_weather(latitude: float, longitude: float) -> dict:
    """Запрашивает погоду для точки на карте и возвращает ответ как словарь Python."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": FIELDS,   # погода прямо сейчас
        "hourly": FIELDS,    # погода по часам
        "past_days": 1,      # плюс вчерашний день, чтобы график был не пустой сразу
        "forecast_days": 1,
        "timezone": "GMT",   # время в UTC, в местное время города переводим на странице
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(WEATHER_URL, params=params)
        response.raise_for_status()  # если сервис ответил ошибкой, здесь будет исключение
        return response.json()


async def search_cities(query: str, count: int = 8) -> list[dict]:
    """Ищет города по названию. Возвращает список вариантов с координатами и страной."""
    params = {"name": query, "count": count, "language": "ru", "format": "json"}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(GEOCODING_URL, params=params)
        response.raise_for_status()
        data = response.json()
    # Если ничего не нашлось, ключа "results" в ответе просто нет.
    return [
        {
            "name": place["name"],
            "admin1": place.get("admin1"),      # область или регион
            "country": place.get("country"),
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "timezone": place.get("timezone"),  # часовой пояс города, например "Europe/Paris"
        }
        for place in data.get("results", [])
    ]


def _to_utc(text: str) -> datetime:
    """Превращает строку '2026-10-22T15:00' в дату с часовым поясом UTC."""
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def parse_current(data: dict) -> dict:
    """Достаёт из ответа одну запись: погоду прямо сейчас."""
    current = data["current"]
    return {
        "recorded_at": _to_utc(current["time"]),
        "temperature": current["temperature_2m"],
        "humidity": current["relative_humidity_2m"],
        "wind_speed": current["wind_speed_10m"],
    }


def parse_past_hours(data: dict, now: datetime | None = None) -> list[dict]:
    """Достаёт почасовые записи, но только прошедшие часы (без прогноза на будущее)."""
    now = now or datetime.now(timezone.utc)
    hourly = data["hourly"]
    rows = []
    for i, time_text in enumerate(hourly["time"]):
        moment = _to_utc(time_text)
        if moment > now:
            break  # дальше идёт прогноз, а мы храним только то, что уже было
        temperature = hourly["temperature_2m"][i]
        if temperature is None:
            continue  # иногда сервис отдаёт пустые значения, их пропускаем
        rows.append({
            "recorded_at": moment,
            "temperature": temperature,
            "humidity": hourly["relative_humidity_2m"][i],
            "wind_speed": hourly["wind_speed_10m"][i],
        })
    return rows
