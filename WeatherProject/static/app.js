// Логика страницы: спросить данные у нашего backend и показать их.

// Какие показатели умеем рисовать на графике.
const METRICS = {
  temperature: { label: "Температура, °C", color: "#f97316" },
  humidity:    { label: "Влажность, %",    color: "#3b82f6" },
  wind_speed:  { label: "Ветер, км/ч",     color: "#10b981" },
};

// Состояние страницы: выбранный город, период, показатель и загруженные данные.
const state = { cities: [], cityId: null, hours: 24, metric: "temperature", points: [] };
let chart = null;

const $ = (id) => document.getElementById(id);

// ---------- Запоминаем выбранный город в браузере ----------

const STORAGE_KEY = "weather.cityId";

function rememberCity(id) {
  try { localStorage.setItem(STORAGE_KEY, String(id)); } catch (e) { /* хранилище недоступно — не страшно */ }
}

function savedCityId() {
  try { return Number(localStorage.getItem(STORAGE_KEY)) || null; } catch (e) { return null; }
}

function currentCity() {
  return state.cities.find((c) => c.id === state.cityId);
}

// ---------- Время ----------

// Перевод времени из базы (UTC) в местное время выбранного города.
function formatTime(isoText, withDate) {
  const options = withDate
    ? { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }
    : { hour: "2-digit", minute: "2-digit" };
  const timeZone = currentCity()?.timezone;
  try {
    return new Date(isoText).toLocaleString("ru-RU", timeZone ? { ...options, timeZone } : options);
  } catch (e) {
    return new Date(isoText).toLocaleString("ru-RU", options); // неизвестный часовой пояс
  }
}

// ---------- Список городов ----------

// GET /api/cities — загрузить мои города и выбрать нужный.
async function loadCities(selectId) {
  const response = await fetch("/api/cities");
  state.cities = await response.json();
  const wanted = selectId ?? savedCityId();
  const exists = state.cities.some((c) => c.id === wanted);
  state.cityId = exists ? wanted : (state.cities[0]?.id ?? null);
  renderCitySelect();
}

function renderCitySelect() {
  const select = $("city-select");
  select.innerHTML = "";
  for (const city of state.cities) {
    const option = document.createElement("option");
    option.value = city.id;
    option.textContent = city.label;
    select.appendChild(option);
  }
  select.value = String(state.cityId);
  $("remove-city").disabled = state.cities.length <= 1; // последний город убрать нельзя
}

$("city-select").addEventListener("change", (event) => {
  state.cityId = Number(event.target.value);
  rememberCity(state.cityId);
  loadAll();
});

// DELETE /api/cities/{id} — убрать город из списка.
$("remove-city").addEventListener("click", async () => {
  const city = currentCity();
  if (!city) return;
  if (!confirm(`Убрать «${city.label}» из списка? Собранные данные останутся в базе.`)) return;
  await fetch(`/api/cities/${city.id}`, { method: "DELETE" });
  await loadCities();
  rememberCity(state.cityId);
  await loadAll();
});

// ---------- Поиск и добавление города ----------

const searchInput = $("city-search");
const resultsList = $("search-results");
let searchTimer = null;

function hideResults() {
  resultsList.hidden = true;
  resultsList.innerHTML = "";
}

function showNote(text) {
  resultsList.innerHTML = "";
  const li = document.createElement("li");
  li.className = "note";
  li.textContent = text;
  resultsList.appendChild(li);
  resultsList.hidden = false;
}

// Ищем не на каждую букву, а через 0,4 секунды после того, как человек перестал печатать.
searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const query = searchInput.value.trim();
  if (query.length < 2) { hideResults(); return; }
  searchTimer = setTimeout(() => searchCities(query), 400);
});

// GET /api/cities/search?q=... — варианты городов с регионом и страной.
async function searchCities(query) {
  showNote("Ищу…");
  const response = await fetch(`/api/cities/search?q=${encodeURIComponent(query)}`);
  if (searchInput.value.trim() !== query) return; // пока ждали, человек уже напечатал другое
  if (!response.ok) { showNote("Поиск сейчас недоступен"); return; }
  const places = await response.json();
  if (places.length === 0) { showNote("Ничего не найдено"); return; }

  resultsList.innerHTML = "";
  for (const place of places) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = place.name;
    const details = document.createElement("small");
    details.textContent = [place.admin1, place.country].filter(Boolean).join(", ");
    button.appendChild(details);
    button.addEventListener("click", () => addCity(place));
    li.appendChild(button);
    resultsList.appendChild(li);
  }
  resultsList.hidden = false;
}

// POST /api/cities — добавить город. Сервер сразу соберёт для него погоду.
async function addCity(place) {
  showNote(`Добавляю ${place.name} и загружаю погоду…`);
  const response = await fetch("/api/cities", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(place),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    showNote(error.detail || "Не удалось добавить город");
    return;
  }
  const city = await response.json();
  searchInput.value = "";
  hideResults();
  await loadCities(city.id);
  rememberCity(city.id);
  await loadAll();
}

// Закрываем список результатов кликом мимо него или клавишей Esc.
document.addEventListener("click", (event) => {
  if (!event.target.closest(".search")) hideResults();
});
searchInput.addEventListener("keydown", (event) => {
  if (event.key === "Escape") hideResults();
});

// ---------- Погода сейчас ----------

function clearCurrent(message) {
  $("temp").textContent = "—";
  $("humidity").textContent = "—";
  $("wind").textContent = "—";
  $("updated").textContent = message;
}

// GET /api/weather/current?city_id=...
async function loadCurrent() {
  const city = currentCity();
  $("city").textContent = city ? city.label : "Погода";
  if (!city) { clearCurrent("Добавьте город через поиск."); return; }

  const response = await fetch(`/api/weather/current?city_id=${city.id}`);
  if (!response.ok) { clearCurrent("Данных пока нет. Нажмите «Обновить сейчас»."); return; }
  const data = await response.json();
  $("temp").textContent = Math.round(data.temperature) + "°";
  $("humidity").textContent = Math.round(data.humidity) + "%";
  $("wind").textContent = data.wind_speed.toFixed(1) + " км/ч";
  $("updated").textContent = "Данные на " + formatTime(data.recorded_at, true) + " по местному времени";
}

// ---------- График ----------

// GET /api/weather/history?city_id=...&hours=...
async function loadHistory() {
  if (!state.cityId) { state.points = []; drawChart(); return; }
  const response = await fetch(`/api/weather/history?city_id=${state.cityId}&hours=${state.hours}`);
  const data = response.ok ? await response.json() : { points: [] };
  state.points = data.points;
  drawChart();
}

function drawChart() {
  const metric = METRICS[state.metric];
  const withDate = state.hours > 24;
  const labels = state.points.map((p) => formatTime(p.recorded_at, withDate));
  const values = state.points.map((p) => p[state.metric]);

  $("empty").hidden = state.points.length > 0;

  if (chart) chart.destroy(); // убираем старый график перед тем, как нарисовать новый
  chart = new Chart($("chart"), {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: metric.label,
        data: values,
        borderColor: metric.color,
        backgroundColor: metric.color + "22",
        fill: true,
        tension: 0.3,
        pointRadius: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { x: { ticks: { maxTicksLimit: 8 } } },
    },
  });
}

async function loadAll() {
  await Promise.all([loadCurrent(), loadHistory()]);
}

// ---------- Кнопки ----------

// POST /api/weather/refresh?city_id=... — собрать погоду сейчас, потом перезагрузить данные.
$("refresh").addEventListener("click", async (event) => {
  if (!state.cityId) return;
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "Обновляю…";
  try {
    await fetch(`/api/weather/refresh?city_id=${state.cityId}`, { method: "POST" });
    await loadAll();
  } finally {
    button.disabled = false;
    button.textContent = "Обновить сейчас";
  }
});

// Переключатель кнопок в группе: подсвечиваем выбранную и запоминаем выбор.
function setupGroup(groupId, onSelect) {
  const group = $(groupId);
  group.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    group.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
    button.classList.add("active");
    onSelect(button);
  });
}

setupGroup("metrics", (button) => {
  state.metric = button.dataset.metric;
  drawChart();            // данные те же, меняем только показатель
});

setupGroup("periods", (button) => {
  state.hours = Number(button.dataset.hours);
  loadHistory();          // другой период — нужно запросить другие данные
});

// ---------- Старт ----------

(async () => {
  await loadCities();
  await loadAll();
})();
setInterval(loadAll, 5 * 60 * 1000); // автообновление каждые 5 минут
