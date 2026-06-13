const { useEffect, useMemo, useRef, useState } = React;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    credentials: "same-origin",
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || data.message || data.details || "Request failed");
  return data;
}

function formatStation(station) {
  if (!station) return "Станция не выбрана";
  return `${station.name || "Station"} · ${station.provider_name || "unknown"} · ${station.location_id}`;
}

function formatDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function drawLineChart(canvas, rows, color, label) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fbfdfe";
  ctx.fillRect(0, 0, width, height);

  if (!rows.length) {
    ctx.fillStyle = "#64748b";
    ctx.font = "16px Arial";
    ctx.fillText("Нет данных", 28, 44);
    return;
  }

  const values = rows.map((row) => Number(row.value));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const top = 34;
  const left = 58;
  const right = 24;
  const bottom = 58;
  const plotW = width - left - right;
  const plotH = height - top - bottom;
  const range = Math.max(max - min, 1);

  ctx.strokeStyle = "#d8e3e8";
  ctx.fillStyle = "#64748b";
  ctx.lineWidth = 1;
  ctx.font = "12px Arial";

  for (let i = 0; i < 5; i += 1) {
    const y = top + (plotH * i) / 4;
    const value = max - (range * i) / 4;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(width - right, y);
    ctx.stroke();
    ctx.fillText(value.toFixed(0), 12, y + 4);
  }

  ctx.strokeStyle = color;
  ctx.lineWidth = 3;
  ctx.beginPath();
  rows.forEach((row, index) => {
    const x = left + (plotW * index) / Math.max(rows.length - 1, 1);
    const y = top + plotH - ((Number(row.value) - min) / range) * plotH;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  const labelIndexes = Array.from(
    new Set([0, Math.floor(rows.length / 4), Math.floor(rows.length / 2), Math.floor((rows.length * 3) / 4), rows.length - 1]),
  );
  ctx.fillStyle = "#475569";
  ctx.font = "12px Arial";
  labelIndexes.forEach((index) => {
    const row = rows[index];
    if (!row) return;
    const x = left + (plotW * index) / Math.max(rows.length - 1, 1);
    ctx.save();
    ctx.translate(x, height - 18);
    ctx.rotate(-Math.PI / 10);
    ctx.fillText(formatDateTime(row.datetime), -30, 0);
    ctx.restore();
  });

  ctx.fillStyle = "#122025";
  ctx.font = "15px Arial";
  ctx.fillText(`${label}: ${min.toFixed(1)}-${max.toFixed(1)} мкг/м³`, left, 22);
}

function LineChart({ rows, color, label, height = 320 }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    drawLineChart(canvasRef.current, rows || [], color, label);
  }, [rows, color, label]);
  return <canvas ref={canvasRef} width="920" height={height}></canvas>;
}

function Header({ user, onLogin, onRegister, onLogout }) {
  return (
    <header className="site-header">
      <a className="brand" href="#home" aria-label="AEROSTAT home">
        <span className="brand-mark"></span>
        <span>AEROSTAT</span>
      </a>
      {!user ? (
        <nav className="public-nav">
          <a href="#problem">Проблема</a>
          <a href="#features">Возможности</a>
          <button className="ghost-btn" onClick={onLogin}>Вход</button>
          <button onClick={onRegister}>Регистрация</button>
        </nav>
      ) : (
        <nav className="app-nav">
          <span>{user.email}</span>
          <button className="ghost-btn" onClick={onLogout}>Выйти</button>
        </nav>
      )}
    </header>
  );
}

function Landing({ onLogin, onRegister }) {
  return (
    <>
      <section className="hero" id="home">
        <div className="hero-copy">
          <p className="eyebrow">SmartScape 2026 · Ecology & Urban Environment</p>
          <h1>Прогноз качества воздуха в Алматы на 24 часа</h1>
          <p>
            AEROSTAT объединяет live-данные OpenAQ, исторический датасет, LSTM-прогноз,
            карту станций и AI-ассистента для понятных решений на каждый день.
          </p>
          <div className="hero-actions">
            <button onClick={onRegister}>Создать аккаунт</button>
            <button className="secondary" onClick={onLogin}>Войти</button>
          </div>
        </div>
        <div className="hero-panel">
          <div className="metric-card primary">
            <span>PM2.5 forecast</span>
            <strong>24h</strong>
            <small>Сегодня + следующие 24 часа</small>
          </div>
          <div className="mini-grid">
            <div><strong>146</strong><span>станций</span></div>
            <div><strong>OpenAQ</strong><span>live API</span></div>
            <div><strong>React</strong><span>dashboard</span></div>
            <div><strong>OSM</strong><span>карта</span></div>
          </div>
        </div>
      </section>
      <section className="info-band" id="problem">
        <div>
          <h2>Проблема</h2>
          <p>
            Воздух в Алматы может резко ухудшаться из-за отопительного сезона, трафика и погодных условий.
            Жителям нужен прогноз заранее, а не только факт загрязнения постфактум.
          </p>
        </div>
        <div>
          <h2>Решение</h2>
          <p>
            Сервис показывает ближайшую станцию, текущие показатели, прогноз на 24 часа,
            рекомендации и доступ к Telegram-боту с уведомлениями.
          </p>
        </div>
      </section>
      <section className="feature-band" id="features">
        <article><h3>Live OpenAQ</h3><p>Текущие измерения берутся через API по координатам пользователя или станции.</p></article>
        <article><h3>LSTM forecast</h3><p>Прогнозные timestamps всегда строятся от текущего времени.</p></article>
        <article><h3>OpenStreetMap</h3><p>На карте можно открыть любую станцию и перейти к прогнозу.</p></article>
        <article><h3>AI assistant</h3><p>Чат получает контекст станции, live-данных и прогноза.</p></article>
      </section>
    </>
  );
}

function AuthModal({ mode, setMode, onClose, onSuccess }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const isLogin = mode === "login";

  async function submit(event) {
    event.preventDefault();
    setMessage("");
    try {
      const payload = await api(isLogin ? "/api/login" : "/api/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      onSuccess(payload.user);
      onClose();
    } catch (error) {
      setMessage(error.message);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target.className === "modal-backdrop" && onClose()}>
      <div className="modal" role="dialog" aria-modal="true">
        <button className="modal-close" onClick={onClose} aria-label="Закрыть">×</button>
        <h2>{isLogin ? "Вход" : "Регистрация"}</h2>
        <div className="auth-tabs">
          <button className={`auth-tab ${isLogin ? "active" : ""}`} onClick={() => setMode("login")}>Вход</button>
          <button className={`auth-tab ${!isLogin ? "active" : ""}`} onClick={() => setMode("register")}>Регистрация</button>
        </div>
        <form id="authForm" onSubmit={submit}>
          <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" placeholder="Email" required />
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" placeholder="Пароль" required />
          <button type="submit">{isLogin ? "Войти" : "Создать аккаунт"}</button>
        </form>
        <p id="authMessage">{message}</p>
      </div>
    </div>
  );
}

function StationMap({ active, stations, selectedId, onSelect }) {
  const mapRef = useRef(null);
  const mapObject = useRef(null);
  const layerGroup = useRef(null);

  useEffect(() => {
    if (!active || !window.L || mapObject.current) return;
    mapObject.current = L.map(mapRef.current, {
      center: [43.238949, 76.889709],
      zoom: 11,
      zoomControl: true,
      scrollWheelZoom: true,
    });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(mapObject.current);
    layerGroup.current = L.layerGroup().addTo(mapObject.current);
    setTimeout(() => mapObject.current.invalidateSize(), 150);
  }, [active]);

  useEffect(() => {
    if (!active || !mapObject.current) return;
    const timers = [80, 250, 600].map((delay) =>
      setTimeout(() => {
        mapObject.current.invalidateSize();
      }, delay),
    );
    return () => timers.forEach(clearTimeout);
  }, [active]);

  useEffect(() => {
    if (!active || !mapObject.current || !layerGroup.current || !stations.length) return;
    layerGroup.current.clearLayers();
    const bounds = [];
    stations.forEach((station) => {
      const lat = Number(station.lat);
      const lon = Number(station.lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
      const marker = L.circleMarker([lat, lon], {
        radius: Number(station.location_id) === Number(selectedId) ? 9 : 6,
        color: Number(station.location_id) === Number(selectedId) ? "#2563eb" : "#0d766f",
        fillColor: Number(station.location_id) === Number(selectedId) ? "#60a5fa" : "#31d1bd",
        fillOpacity: 0.9,
        weight: 2,
      });
      marker.bindPopup(`
        <strong>${station.name || "Station"}</strong><br>
        ${station.provider_name || "unknown"}<br>
        ID: ${station.location_id}<br>
        <button type="button" class="map-popup-btn">Открыть станцию</button>
      `);
      marker.on("popupopen", () => {
        setTimeout(() => {
          const button = document.querySelector(".map-popup-btn");
          if (button) button.onclick = () => onSelect(station.location_id);
        }, 0);
      });
      marker.addTo(layerGroup.current);
      bounds.push([lat, lon]);
    });
    if (bounds.length) {
      mapObject.current.fitBounds(bounds, { padding: [24, 24] });
      setTimeout(() => mapObject.current.invalidateSize(), 100);
      setTimeout(() => mapObject.current.invalidateSize(), 400);
    }
  }, [active, stations, selectedId]);

  return <div ref={mapRef} id="stationMap" className="map"></div>;
}

function Dashboard({ user, config, stations }) {
  const [activeTab, setActiveTab] = useState("nearest");
  const [selectedId, setSelectedId] = useState(stations[0]?.location_id || null);
  const [stationInfo, setStationInfo] = useState("Отправьте геолокацию или выберите станцию на карте.");
  const [currentPm25, setCurrentPm25] = useState("--");
  const [currentInfo, setCurrentInfo] = useState("OpenAQ live");
  const [forecast, setForecast] = useState([]);
  const [history, setHistory] = useState([]);
  const [forecastSummary, setForecastSummary] = useState("Выберите станцию.");
  const [forecastPeak, setForecastPeak] = useState("--");
  const [forecastStatus, setForecastStatus] = useState("24 часа");
  const [chatMessages, setChatMessages] = useState([]);
  const [question, setQuestion] = useState("");

  const selectedStation = useMemo(
    () => stations.find((station) => Number(station.location_id) === Number(selectedId)),
    [stations, selectedId],
  );

  useEffect(() => {
    if (!selectedId && stations.length) {
      setSelectedId(stations[0].location_id);
    }
  }, [stations, selectedId]);

  useEffect(() => {
    if (selectedStation) {
      setStationInfo(`${formatStation(selectedStation)} · ${Number(selectedStation.lat).toFixed(4)}, ${Number(selectedStation.lon).toFixed(4)}`);
    }
  }, [selectedStation]);

  async function refreshCurrent(id = selectedId) {
    if (!id) return;
    setCurrentPm25("--");
    setCurrentInfo("Запрос OpenAQ...");
    try {
      const payload = await api(`/api/current?location_id=${id}&pollutants=pm25,pm10,pm1`);
      const point = payload.points?.find((item) => Number(item.locationId) === Number(id)) || payload.points?.[0];
      const pm25 = point?.measurements?.pm25;
      if (pm25) {
        setCurrentPm25(Number(pm25.value).toFixed(1));
        setCurrentInfo(`${formatDateTime(pm25.observedAt)} · ${point.name}`);
      } else {
        setCurrentInfo("Свежих PM2.5 измерений рядом нет.");
      }
    } catch (error) {
      setCurrentInfo(error.message);
    }
  }

  async function refreshHistory(id = selectedId) {
    if (!id) return;
    const payload = await api(`/api/history?location_id=${id}&limit=168`);
    setHistory(payload.history || []);
  }

  async function refreshForecast(id = selectedId) {
    if (!id) return;
    setForecastSummary("Строю прогноз...");
    const payload = await api(`/api/forecast?location_id=${id}`);
    const rows = payload.forecast || [];
    setForecast(rows);
    const values = rows.map((row) => Number(row.value));
    if (!values.length) return;
    const peak = Math.max(...values);
    const peakPoint = rows[values.indexOf(peak)];
    const status = peakPoint?.status || {};
    setForecastPeak(peak.toFixed(1));
    setForecastStatus(`${status.label || "статус недоступен"} · ${formatDateTime(peakPoint.datetime)}`);
    setForecastSummary(`Пик ${peak.toFixed(1)} мкг/м³ в ${formatDateTime(peakPoint.datetime)}. ${status.advice || ""}`);
  }

  async function refreshAll(id = selectedId) {
    await Promise.all([refreshCurrent(id), refreshHistory(id), refreshForecast(id)]);
  }

  useEffect(() => {
    if (selectedId) refreshAll(selectedId);
  }, [selectedId]);

  function findNearest() {
    if (!navigator.geolocation) {
      setStationInfo("Геолокация недоступна в браузере.");
      return;
    }
    setStationInfo("Получаю геолокацию...");
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        try {
          const { latitude, longitude } = position.coords;
          const payload = await api(`/api/nearest-station?lat=${latitude}&lon=${longitude}`);
          setSelectedId(payload.station.location_id);
          setActiveTab("nearest");
          setStationInfo(`${formatStation(payload.station)} · расстояние ${payload.station.distance_km} км`);
        } catch (error) {
          setStationInfo(error.message);
        }
      },
      () => setStationInfo("Не удалось получить геолокацию."),
    );
  }

  async function askAgent(event) {
    event.preventDefault();
    const cleanQuestion = question.trim();
    if (!cleanQuestion) return;
    setQuestion("");
    setChatMessages((items) => [...items, { role: "user", text: cleanQuestion }, { role: "assistant", text: "Думаю над ответом..." }]);
    try {
      const payload = await api("/api/agent/ask", {
        method: "POST",
        body: JSON.stringify({ question: cleanQuestion, location_id: selectedId }),
      });
      setChatMessages((items) => [...items.slice(0, -1), { role: "assistant", text: payload.answer }]);
    } catch (error) {
      setChatMessages((items) => [...items.slice(0, -1), { role: "assistant", text: error.message }]);
    }
  }

  function openStationFromMap(id) {
    setSelectedId(id);
    setActiveTab("nearest");
  }

  const chatContext = selectedStation
    ? `Станция: ${formatStation(selectedStation)}. Live PM2.5: ${currentPm25}. Пик прогноза: ${forecastPeak}.`
    : "Контекст появится после выбора станции.";

  return (
    <section className="dashboard">
      <aside className="sidebar">
        <div className="sidebar-title"><span className="brand-mark"></span><strong>Кабинет</strong></div>
        {["nearest", "map", "chat", "bot"].map((tab) => (
          <button key={tab} className={`tab-btn ${activeTab === tab ? "active" : ""}`} onClick={() => setActiveTab(tab)}>
            {tab === "nearest" ? "Ближайшая" : tab === "map" ? "Карта" : tab === "chat" ? "AI-чат" : "Telegram-бот"}
          </button>
        ))}
      </aside>

      <div className="workspace">
        {activeTab === "nearest" && (
          <section className="tab-panel active">
            <div className="workspace-header">
              <div>
                <p className="eyebrow">Персональная точка мониторинга</p>
                <h2>Ближайшая станция и прогноз</h2>
              </div>
              <div className="header-actions">
                <button onClick={findNearest}>Найти по геолокации</button>
                <button className="secondary" onClick={() => refreshAll()}>Обновить</button>
              </div>
            </div>

            <div className="summary-grid">
              <div className="summary-card wide">
                <span>Выбранная станция</span>
                <strong>{selectedStation?.name || "Станция не выбрана"}</strong>
                <small>{stationInfo}</small>
              </div>
              <div className="summary-card"><span>Live PM2.5</span><strong>{currentPm25}</strong><small>{currentInfo}</small></div>
              <div className="summary-card"><span>Пик прогноза</span><strong>{forecastPeak}</strong><small>{forecastStatus}</small></div>
            </div>

            <div className="controls-row">
              <label>
                Станция
                <select value={selectedId || ""} onChange={(event) => setSelectedId(event.target.value)}>
                  {stations.map((station) => <option key={station.location_id} value={station.location_id}>{formatStation(station)}</option>)}
                </select>
              </label>
              <button onClick={() => refreshForecast()}>Построить прогноз</button>
            </div>

            <div className="chart-grid">
              <section className="chart-panel">
                <div className="section-header"><div><h3>Прогноз PM2.5</h3><p>{forecastSummary}</p></div></div>
                <LineChart rows={forecast} color="#2563eb" label="Прогноз PM2.5" height={330} />
              </section>
              <section className="chart-panel">
                <div className="section-header"><div><h3>История измерений</h3><p>Отображается как последние часы относительно сегодняшней даты.</p></div></div>
                <LineChart rows={history} color="#0d766f" label="История PM2.5" height={300} />
              </section>
            </div>
          </section>
        )}

        {activeTab === "map" && (
          <section className="tab-panel active">
            <div className="workspace-header"><div><p className="eyebrow">OpenStreetMap</p><h2>Карта станций Алматы</h2></div></div>
            <StationMap active={activeTab === "map"} stations={stations} selectedId={selectedId} onSelect={openStationFromMap} />
            <p className="map-note">Нажмите на маркер, чтобы открыть станцию и построить прогноз.</p>
          </section>
        )}

        {activeTab === "chat" && (
          <section className="tab-panel active">
            <div className="workspace-header"><div><p className="eyebrow">xAI/Grok context agent</p><h2>AI-чат по качеству воздуха</h2></div></div>
            <div className="chat-shell">
              <div className="chat-context">{chatContext}</div>
              <div className="chat-log">
                {chatMessages.map((message, index) => <div key={index} className={`chat-message ${message.role}`}>{message.text}</div>)}
              </div>
              <form className="chat-form" onSubmit={askAgent}>
                <input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Например: можно ли завтра утром идти на пробежку?" />
                <button type="submit">Спросить</button>
              </form>
            </div>
          </section>
        )}

        {activeTab === "bot" && (
          <section className="tab-panel active">
            <div className="workspace-header"><div><p className="eyebrow">Telegram push channel</p><h2>Telegram-бот AEROSTAT</h2></div></div>
            <div className="bot-card">
              <p>Бот принимает геолокацию, находит ближайшую станцию, показывает прогноз, отправляет уведомления и отвечает на вопросы.</p>
              {config.telegramBotUrl ? (
                <a className="button-link" href={config.telegramBotUrl} target="_blank" rel="noreferrer">Открыть Telegram-бота</a>
              ) : (
                <small>Укажите TELEGRAM_BOT_USERNAME в .env, чтобы ссылка открывала вашего бота.</small>
              )}
            </div>
          </section>
        )}
      </div>
    </section>
  );
}

function App() {
  const [user, setUser] = useState(null);
  const [stations, setStations] = useState([]);
  const [config, setConfig] = useState({});
  const [authMode, setAuthMode] = useState(null);

  useEffect(() => {
    async function boot() {
      const [configPayload, stationsPayload, mePayload] = await Promise.all([
        api("/api/config").catch(() => ({})),
        api("/api/stations"),
        api("/api/me"),
      ]);
      setConfig(configPayload || {});
      setStations(stationsPayload.stations || []);
      setUser(mePayload.user || null);
    }
    boot().catch((error) => console.error(error));
  }, []);

  async function logout() {
    await api("/api/logout", { method: "POST", body: "{}" });
    setUser(null);
  }

  return (
    <>
      <Header user={user} onLogin={() => setAuthMode("login")} onRegister={() => setAuthMode("register")} onLogout={logout} />
      <main>
        {user ? (
          <Dashboard user={user} config={config} stations={stations} />
        ) : (
          <Landing onLogin={() => setAuthMode("login")} onRegister={() => setAuthMode("register")} />
        )}
      </main>
      {authMode && (
        <AuthModal
          mode={authMode}
          setMode={setAuthMode}
          onClose={() => setAuthMode(null)}
          onSuccess={setUser}
        />
      )}
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
