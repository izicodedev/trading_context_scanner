const state = {
  status: null,
  history: [],
  components: [],
  entries: [],
  evaluation: [],
};

const scoreThreshold = 65;

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || value === "N/D" || value === "") return "N/D";
  const num = Number(value);
  if (Number.isNaN(num)) return "N/D";
  return num.toLocaleString("pt-BR", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function formatDate(value) {
  if (!value || value === "N/D") return "N/D";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function setBadge(id, label, kind) {
  const node = document.getElementById(id);
  if (!node) return;
  node.textContent = label;
  node.className = `status-badge ${kind}`;
}

function renderStatus() {
  const status = state.status || {};
  setBadge("statusBadge", status.scanner_status || "OFFLINE", (status.scanner_status === "ONLINE" ? "online" : "offline"));
  setText("marketValue", status.market || "N/D");
  setText("timeframeValue", status.timeframe || "N/D");
  setText("thresholdValue", `Threshold: ${status.threshold ?? "N/D"}`);
  setText("priceValue", formatNumber(status.price, 2));
  setText("lastUpdateValue", `Última atualização: ${formatDate(status.last_update)}`);
  setText("longScoreValue", status.long_score && status.long_score !== "N/D" ? `${status.long_score}` : "N/D");
  setText("shortScoreValue", status.short_score && status.short_score !== "N/D" ? `${status.short_score}` : "N/D");
  setText("stateValue", status.state || "N/D");
  setText("stateMeta", status.signal_state || "N/D");
  setText("atrValue", "N/D");
  setText("rsiValue", "N/D");
  setText("volRatioValue", "N/D");
  setText("trendValue", "N/D");

  const latest = state.history[0] || {};
  if (latest) {
    const latestLong = Number.isFinite(Number(latest.long_score)) ? Number(latest.long_score) : null;
    const latestShort = Number.isFinite(Number(latest.short_score)) ? Number(latest.short_score) : null;
    const latestPrice = Number.isFinite(Number(latest.price_float ?? latest.price)) ? Number(latest.price_float ?? latest.price) : null;
    setText("priceValue", latestPrice === null ? "N/D" : formatNumber(latestPrice, 2));
    setText("longScoreValue", latestLong === null ? "N/D" : `${latestLong}`);
    setText("shortScoreValue", latestShort === null ? "N/D" : `${latestShort}`);
    setText("stateValue", latest.entry_state || latest.signal_state || "N/D");
    setText("stateMeta", `Signal: ${latest.signal_state || "N/D"} · Setup: ${latest.setup_state || "N/D"}`);
    setText("atrValue", latest.atr === null || latest.atr === undefined ? "N/D" : formatNumber(latest.atr, 4));
    setText("rsiValue", latest.rsi === null || latest.rsi === undefined ? "N/D" : formatNumber(latest.rsi, 2));
    setText("volRatioValue", latest.vol_ratio === null || latest.vol_ratio === undefined ? "N/D" : formatNumber(latest.vol_ratio, 3));
    setText("trendValue", latest.trend_bias || "N/D");
  }

  const longScore = Number.isFinite(Number(latest.long_score)) ? Number(latest.long_score) : 0;
  const shortScore = Number.isFinite(Number(latest.short_score)) ? Number(latest.short_score) : 0;
  const longPercent = Number.isFinite(Number(latest.long_score)) ? Math.min(100, (longScore / scoreThreshold) * 100) : 0;
  const shortPercent = Number.isFinite(Number(latest.short_score)) ? Math.min(100, (shortScore / scoreThreshold) * 100) : 0;
  document.getElementById("longBar").style.width = `${longPercent}%`;
  document.getElementById("shortBar").style.width = `${shortPercent}%`;
  document.getElementById("longBarLabel").textContent = Number.isFinite(Number(latest.long_score)) ? `${longScore}/${scoreThreshold}` : `N/D/${scoreThreshold}`;
  document.getElementById("shortBarLabel").textContent = Number.isFinite(Number(latest.short_score)) ? `${shortScore}/${scoreThreshold}` : `N/D/${scoreThreshold}`;

  const stats = [
    ["Status de scanner", status.scanner_status || "OFFLINE"],
    ["Última atualização", formatDate(status.last_update)],
    ["Total de sinais", String(status.signals_total ?? 0)],
    ["Total de setups", String(status.setup_total ?? 0)],
    ["Total de entries", String(status.entries_total ?? 0)],
    ["Último arquivo", formatDate(status.last_file_update)],
  ];

  const list = document.getElementById("statusList");
  list.innerHTML = stats.map(([label, value]) => `<li><span>${label}</span><strong>${value}</strong></li>`).join("");
}

function renderComponents() {
  const longList = document.getElementById("longComponents");
  const shortList = document.getElementById("shortComponents");

  const long = state.components.filter((item) => item.name.startsWith("long_"));
  const short = state.components.filter((item) => item.name.startsWith("short_"));

  const render = (items) => {
    if (!items.length) {
      return "<li><span>N/D — dados de componentes não registrados pelo scanner.</span></li>";
    }
    return items.map((item) => {
      const pointValue = Number(item.points_total || 0);
      const active = item.activation_count > 0;
      return `<li><div><strong>${item.name}</strong><span>${active ? "Ativo" : "Inativo"}</span></div><div><strong>${active ? `+${pointValue}` : "0"}</strong></div></li>`;
    }).join("");
  };

  longList.innerHTML = render(long);
  shortList.innerHTML = render(short);
}

function renderHistory() {
  const rows = state.history.slice(0, 20);
  const tbody = document.getElementById("historyTableBody");
  tbody.innerHTML = rows.map((row) => {
    const longScore = Number.isFinite(Number(row.long_score)) ? Number(row.long_score) : "N/D";
    const shortScore = Number.isFinite(Number(row.short_score)) ? Number(row.short_score) : "N/D";
    return `
      <tr>
        <td>${formatDate(row.timestamp)}</td>
        <td>${formatNumber(row.price_float ?? row.price, 2)}</td>
        <td>${longScore}</td>
        <td>${shortScore}</td>
        <td>${row.side || row.entry_state || "WAIT"}</td>
        <td><span class="badge ${String((row.signal_state || "SIGNAL")).toLowerCase()}">${row.signal_state || "SIGNAL"}</span></td>
        <td><span class="badge ${String((row.setup_state || "UNSET")).toLowerCase()}">${row.setup_state || "UNSET"}</span></td>
        <td><span class="badge ${String((row.entry_state || "UNSET")).toLowerCase()}">${row.entry_state || "UNSET"}</span></td>
        <td>${formatNumber(row.rsi, 2)}</td>
        <td>${formatNumber(row.atr, 4)}</td>
        <td>${formatNumber(row.vol_ratio, 3)}</td>
        <td>${row.trend_bias || "N/D"}</td>
      </tr>
    `;
  }).join("");
}

function renderEntries() {
  const entries = state.entries;
  const node = document.getElementById("entriesSummary");
  if (!entries.length) {
    node.textContent = "Nenhuma ENTRY registrada.";
    return;
  }

  node.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Timestamp</th>
          <th>Direção</th>
          <th>Preço</th>
          <th>Score</th>
          <th>Threshold</th>
          <th>RSI</th>
          <th>ATR</th>
          <th>Volume</th>
        </tr>
      </thead>
      <tbody>
        ${entries.map((row) => `
          <tr>
            <td>${formatDate(row.timestamp)}</td>
            <td>${row.side || "N/D"}</td>
            <td>${formatNumber(row.price_float ?? row.price, 2)}</td>
            <td>${row.score || row.score_int || "N/D"}</td>
            <td>${scoreThreshold}</td>
            <td>${formatNumber(row.rsi, 2)}</td>
            <td>${formatNumber(row.atr, 4)}</td>
            <td>${formatNumber(row.vol_ratio, 3)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function renderEvaluation() {
  const evaluations = state.evaluation || [];
  const node = document.getElementById("evaluationSummary");
  if (!evaluations.length) {
    node.textContent = "N/D";
    return;
  }
  const latest = evaluations[evaluations.length - 1];
  node.innerHTML = `
    <ul class="status-list">
      <li><span>Resultado 1 candle</span><strong>${formatNumber(latest.ret_1, 4)}</strong></li>
      <li><span>Resultado 3 candles</span><strong>${formatNumber(latest.ret_3, 4)}</strong></li>
      <li><span>Resultado 5 candles</span><strong>${formatNumber(latest.ret_5, 4)}</strong></li>
      <li><span>Resultado 10 candles</span><strong>${formatNumber(latest.ret_10, 4)}</strong></li>
      <li><span>MFE</span><strong>${formatNumber(latest.mfe, 4)}</strong></li>
      <li><span>MAE</span><strong>${formatNumber(latest.mae, 4)}</strong></li>
      <li><span>Outcome</span><strong>${latest.outcome || "N/D"}</strong></li>
    </ul>
  `;
}

function buildLineChart(values, color, backgroundColor) {
  if (!values.length) return "";
  const width = 480;
  const height = 180;
  const padding = 18;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = Math.max(max - min, 1);
  const points = values.map((value, index) => {
    const x = padding + (index / Math.max(values.length - 1, 1)) * (width - padding * 2);
    const y = height - padding - ((value - min) / range) * (height - padding * 2);
    return `${x},${y}`;
  }).join(" ");
  return `
    <defs>
      <linearGradient id="grad-${color.replace('#', '')}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${color}" stop-opacity="0.7" />
        <stop offset="100%" stop-color="${backgroundColor}" stop-opacity="0.05" />
      </linearGradient>
    </defs>
    <polyline fill="none" stroke="${color}" stroke-width="2" points="${points}" />
  `;
}

function renderCharts() {
  const history = state.history.slice().reverse();
  const priceValues = history.map((row) => Number(row.price_float ?? row.price ?? 0));
  const longValues = history.map((row) => Number(row.long_score ?? 0));
  const shortValues = history.map((row) => Number(row.short_score ?? 0));
  const rsiValues = history.map((row) => Number(row.rsi ?? 50));
  const volValues = history.map((row) => Number(row.vol_ratio ?? 1));

  document.getElementById("priceChart").innerHTML = buildLineChart(priceValues, "#60a5fa", "#0b1220");
  document.getElementById("scoreChart").innerHTML = buildLineChart(longValues, "#22c55e", "#0b1220") + buildLineChart(shortValues, "#ef4444", "#0b1220");
  document.getElementById("rsiChart").innerHTML = buildLineChart(rsiValues, "#fbbf24", "#0b1220");
  document.getElementById("volChart").innerHTML = buildLineChart(volValues, "#a78bfa", "#0b1220");
}

async function loadData() {
  try {
    const [status, history, components, entries, evaluation] = await Promise.all([
      fetch("/api/status").then((r) => r.json()),
      fetch("/api/history?limit=200").then((r) => r.json()),
      fetch("/api/components").then((r) => r.json()),
      fetch("/api/entries").then((r) => r.json()),
      fetch("/api/evaluation").then((r) => r.json()),
    ]);

    state.status = status;
    state.history = history;
    state.components = components;
    state.entries = entries;
    state.evaluation = evaluation;

    renderStatus();
    renderHistory();
    renderComponents();
    renderEntries();
    renderEvaluation();
    renderCharts();
  } catch (error) {
    console.error("Erro ao carregar dados do dashboard", error);
    setBadge("statusBadge", "OFFLINE", "offline");
    document.getElementById("entriesSummary").textContent = "N/D";
  }
}

window.addEventListener("DOMContentLoaded", loadData);
setInterval(loadData, 15000);
