"""Работа с базой данных PostgreSQL.

Две таблицы:
- cities  — города, которые мы отслеживаем;
- weather — сами записи о погоде. Колонка city хранит подпись города, например «Париж, Франция».
"""
import psycopg
from psycopg.rows import dict_row

from config import DATABASE_URL

CITY_COLUMNS = "id, label, name, country, latitude, longitude, timezone"


def get_conn():
    """Открывает соединение. dict_row значит, что строки приходят как словари: row["temperature"]."""
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def make_label(name: str, admin1: str | None, country: str | None) -> str:
    """Подпись города: «Город, Регион, Страна». Регион пропускаем, если он совпадает с городом."""
    parts = [name]
    if admin1 and admin1 != name:
        parts.append(admin1)
    if country:
        parts.append(country)
    return ", ".join(parts)


def create_tables(default_city: dict):
    """Создаёт таблицы, если их нет, и добавляет город по умолчанию при самом первом запуске."""
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weather (
                id          SERIAL PRIMARY KEY,
                city        TEXT        NOT NULL,
                recorded_at TIMESTAMPTZ NOT NULL,
                temperature REAL        NOT NULL,
                humidity    REAL,
                wind_speed  REAL,
                -- одна и та же минута для одного города хранится только один раз
                UNIQUE (city, recorded_at)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cities (
                id        SERIAL PRIMARY KEY,
                label     TEXT NOT NULL UNIQUE,
                name      TEXT NOT NULL,
                country   TEXT,
                latitude  DOUBLE PRECISION NOT NULL,
                longitude DOUBLE PRECISION NOT NULL,
                timezone  TEXT
            )
            """
        )
        has_cities = conn.execute("SELECT EXISTS (SELECT 1 FROM cities)").fetchone()["exists"]
        if not has_cities:
            label = make_label(default_city["name"], default_city["admin1"], default_city["country"])
            conn.execute(
                """
                INSERT INTO cities (label, name, country, latitude, longitude, timezone)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (label, default_city["name"], default_city["country"],
                 default_city["latitude"], default_city["longitude"], default_city["timezone"]),
            )
            # В первой версии проекта записи хранились под названием «Бишкек».
            # Переименовываем их, чтобы старая история не потерялась.
            conn.execute("UPDATE weather SET city = %s WHERE city = %s", (label, default_city["name"]))


# ---------- Города ----------

def list_cities() -> list[dict]:
    with get_conn() as conn:
        return conn.execute(f"SELECT {CITY_COLUMNS} FROM cities ORDER BY id").fetchall()


def get_city(city_id: int) -> dict | None:
    with get_conn() as conn:
        return conn.execute(f"SELECT {CITY_COLUMNS} FROM cities WHERE id = %s", (city_id,)).fetchone()


def count_cities() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT count(*) AS n FROM cities").fetchone()["n"]


def add_city(place: dict) -> dict:
    """Добавляет город. Если такой уже есть (те же координаты или та же подпись), возвращает существующий."""
    with get_conn() as conn:
        # Один и тот же город может называться по-разному («Кыргызстан» и «Киргизия»),
        # поэтому сначала ищем по координатам: всё, что ближе ~5 км, считаем тем же городом.
        existing = conn.execute(
            f"""
            SELECT {CITY_COLUMNS} FROM cities
            WHERE abs(latitude - %s) < 0.05 AND abs(longitude - %s) < 0.05
            LIMIT 1
            """,
            (place["latitude"], place["longitude"]),
        ).fetchone()
        if existing:
            return existing
        label = make_label(place["name"], place.get("admin1"), place.get("country"))
        return conn.execute(
            f"""
            INSERT INTO cities (label, name, country, latitude, longitude, timezone)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (label) DO UPDATE SET label = EXCLUDED.label
            RETURNING {CITY_COLUMNS}
            """,
            (label, place["name"], place.get("country"),
             place["latitude"], place["longitude"], place.get("timezone")),
        ).fetchone()


def delete_city(city_id: int) -> bool:
    """Убирает город из списка. Записи о погоде остаются в базе: если вернуть город, история вернётся."""
    with get_conn() as conn:
        return conn.execute("DELETE FROM cities WHERE id = %s", (city_id,)).rowcount > 0


# ---------- Погода ----------

def save_rows(city_label: str, rows: list[dict]) -> int:
    """Сохраняет записи. Повторы молча пропускаются. Возвращает, сколько записей реально добавлено."""
    added = 0
    with get_conn() as conn:
        for row in rows:
            cursor = conn.execute(
                """
                INSERT INTO weather (city, recorded_at, temperature, humidity, wind_speed)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (city, recorded_at) DO NOTHING
                """,
                (city_label, row["recorded_at"], row["temperature"], row["humidity"], row["wind_speed"]),
            )
            added += cursor.rowcount  # 1 — добавили, 0 — такая запись уже была
    return added


def get_latest(city_label: str) -> dict | None:
    """Самая свежая запись для города."""
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT recorded_at, temperature, humidity, wind_speed
            FROM weather
            WHERE city = %s
            ORDER BY recorded_at DESC
            LIMIT 1
            """,
            (city_label,),
        ).fetchone()


def get_history(city_label: str, hours: int) -> list[dict]:
    """Все записи за последние N часов, от старых к новым (так удобно рисовать график)."""
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT recorded_at, temperature, humidity, wind_speed
            FROM weather
            WHERE city = %s
              AND recorded_at >= now() - %s * interval '1 hour'
            ORDER BY recorded_at
            """,
            (city_label, hours),
        ).fetchall()
