"""Главный файл: запускает сервер, сборщик погоды по расписанию и отдаёт страницу."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import weather_client
from config import DEFAULT_CITY, FETCH_INTERVAL_MINUTES, MAX_CITIES

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger("weather")

STATIC_DIR = Path(__file__).parent / "static"


# ---------- Сбор погоды ----------

async def collect_city(city: dict) -> int:
    """Один сбор для одного города: скачать погоду, разобрать ответ, сохранить в базу."""
    data = await weather_client.fetch_weather(city["latitude"], city["longitude"])
    rows = weather_client.parse_past_hours(data)        # прошедшие часы (заполняют пробелы)
    rows.append(weather_client.parse_current(data))     # и погода прямо сейчас
    # Работа с базой не асинхронная, поэтому выполняем её в отдельном потоке,
    # чтобы сервер в это время продолжал отвечать на запросы.
    added = await asyncio.to_thread(db.save_rows, city["label"], rows)
    log.info("%s: новых записей %s", city["label"], added)
    return added


async def collect_all():
    """Собрать погоду для всех городов из списка. Ошибка в одном городе не мешает остальным."""
    cities = await asyncio.to_thread(db.list_cities)
    for city in cities:
        try:
            await collect_city(city)
        except Exception as error:
            log.warning("%s: не удалось получить погоду: %s", city["label"], error)


async def collector_loop():
    """Бесконечный цикл: собрать погоду для всех городов, подождать, повторить."""
    while True:
        try:
            await collect_all()
        except Exception as error:
            # Например, база данных недоступна. Сервер не падает, а пробует в следующий раз.
            log.warning("Сбор погоды не удался: %s", error)
        await asyncio.sleep(FETCH_INTERVAL_MINUTES * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Что сделать при запуске сервера и при его остановке."""
    db.create_tables(DEFAULT_CITY)
    task = asyncio.create_task(collector_loop())  # сборщик работает в фоне
    yield                                          # здесь сервер работает
    task.cancel()                                  # сервер остановили — останавливаем сборщик


app = FastAPI(title="Погода", lifespan=lifespan)


def require_city(city_id: int) -> dict:
    """Находит город по id или отвечает ошибкой 404."""
    city = db.get_city(city_id)
    if city is None:
        raise HTTPException(status_code=404, detail="Город не найден")
    return city


# ---------- Города ----------

class CityIn(BaseModel):
    """Данные о городе, которые присылает страница при добавлении (берутся из результата поиска)."""
    name: str
    admin1: str | None = None
    country: str | None = None
    latitude: float
    longitude: float
    timezone: str | None = None


@app.get("/api/cities")
def list_cities():
    """Все города, которые мы отслеживаем."""
    return db.list_cities()


@app.get("/api/cities/search")
async def search_cities(q: str = Query(..., min_length=2)):
    """Поиск города по названию через Open-Meteo."""
    try:
        return await weather_client.search_cities(q)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Поиск недоступен: {error}")


@app.post("/api/cities", status_code=201)
async def add_city(place: CityIn):
    """Добавить город в список и сразу собрать для него погоду."""
    if db.count_cities() >= MAX_CITIES:
        raise HTTPException(status_code=400, detail=f"Можно отслеживать не больше {MAX_CITIES} городов")
    city = db.add_city(place.model_dump())
    try:
        await collect_city(city)  # чтобы данные и график появились сразу, а не через 15 минут
    except Exception as error:
        log.warning("%s: не удалось получить погоду: %s", city["label"], error)
    return city


@app.delete("/api/cities/{city_id}")
def delete_city(city_id: int):
    """Убрать город из списка (история погоды остаётся в базе)."""
    require_city(city_id)
    if db.count_cities() <= 1:
        raise HTTPException(status_code=400, detail="Нельзя убрать последний город")
    db.delete_city(city_id)
    return {"deleted": city_id}


# ---------- Погода ----------

@app.get("/api/weather/current")
def current_weather(city_id: int):
    """Последняя сохранённая погода для города."""
    city = require_city(city_id)
    row = db.get_latest(city["label"])
    if row is None:
        raise HTTPException(status_code=404, detail="Данных пока нет")
    return {"city": city["label"], **row}


@app.get("/api/weather/history")
def weather_history(city_id: int, hours: int = Query(24, ge=1, le=168)):
    """История за последние N часов (от 1 до 168, то есть до недели)."""
    city = require_city(city_id)
    return {"city": city["label"], "points": db.get_history(city["label"], hours)}


@app.post("/api/weather/refresh")
async def refresh_now(city_id: int):
    """Собрать погоду для города прямо сейчас, не дожидаясь расписания."""
    city = require_city(city_id)
    try:
        added = await collect_city(city)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Сервис погоды недоступен: {error}")
    return {"added": added}


# ---------- Страница ----------

@app.get("/")
def index():
    """Главная страница сайта."""
    return FileResponse(STATIC_DIR / "index.html")


# Файлы страницы (стили и скрипт) раздаются по адресу /static/...
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
