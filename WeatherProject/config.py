"""Настройки проекта. Всё, что может поменяться, собрано здесь, в одном месте."""
import os

from dotenv import load_dotenv

# Секреты (пароль базы) хранятся не в коде, а в файле .env рядом с проектом.
# Файл .env не выкладывается на GitHub. На Render те же значения задаются в разделе Environment.
load_dotenv()

# Город, который добавляется сам при самом первом запуске.
# Остальные города добавляются прямо на сайте через поиск.
DEFAULT_CITY = {
    "name": "Бишкек",
    "admin1": None,
    "country": "Кыргызстан",
    "latitude": 42.8746,
    "longitude": 74.5698,
    "timezone": "Asia/Bishkek",
}

# Сколько городов можно отслеживать одновременно (чтобы не заваливать сервис погоды запросами).
MAX_CITIES = 10

# Как часто забирать погоду, в минутах.
# Сервис Open-Meteo обновляет текущие данные раз в 15 минут, чаще спрашивать нет смысла.
FETCH_INTERVAL_MINUTES = int(os.getenv("FETCH_INTERVAL_MINUTES", "15"))

# Адрес базы данных. Берётся из переменной DATABASE_URL (файл .env или настройки хостинга).
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Не задан DATABASE_URL. Создайте файл .env (пример в .env.example).")
