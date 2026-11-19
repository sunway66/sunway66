"use strict";

/* -------------------------------------------------------------------------- */
/* Utilities                                                                  */
/* -------------------------------------------------------------------------- */

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const integerFormatter = new Intl.NumberFormat("zh-CN", {
  maximumFractionDigits: 0,
});

const numberFormatter = new Intl.NumberFormat("zh-CN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const state = {
  data: null,
  range: readRange(),
  charts: { breadth: null, net: null, scale: null },
  chartLoader: null,
};

function readRange() {
  try {
    const saved = Number(localStorage.getItem("shunwei-range"));
    return [30, 90, 180].includes(saved) ? saved : 180;
  } catch (error) {
    return 180;
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[character]));
}

function formatInteger(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return integerFormatter.format(number);
}

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return numberFormatter.format(number);
}

function formatSigned(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  if (Math.abs(number) < 0.005) return "0.00";
  return `${number > 0 ? "+" : ""}${numberFormatter.format(number)}`;
}

function formatAxis(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  if (Math.abs(number) >= 10000) {
    return `${(number / 10000).toFixed(1).replace(/\.0$/, "")}万`;
  }
  return integerFormatter.format(number);
}

function splitIsoDate(iso) {
  if (typeof iso !== "string") return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return null;
  return { year: match[1], month: match[2], day: match[3] };
}

function formatChineseDate(iso) {
  const parts = splitIsoDate(iso);
  if (!parts) return "—";
  return `${parts.year}年${Number(parts.month)}月${Number(parts.day)}日`;
}

function formatShortDate(iso) {
  const parts = splitIsoDate(iso);
  if (!parts) return "";
  return `${parts.month}/${parts.day}`;
}

function formatDateDot(iso) {
  const parts = splitIsoDate(iso);
  if (!parts) return "—";
  return `${parts.year}.${parts.month}.${parts.day}`;
}

function formatDateTime(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatTurnover(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  if (Math.abs(number) >= 10000) {
    return `${(number / 10000).toFixed(2)} 万亿`;
  }
  return `${numberFormatter.format(number)} 亿`;
}

function formatTurnoverPart(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return `${numberFormatter.format(number)} 亿`;
}

function findLastIndex(values, predicate) {
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (predicate(values[index], index)) return index;
  }
  return -1;
}

function cssValue(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function showToast(message, timeout = 2800) {
  const toast = $("#toast");
  if (!toast) return;
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toast.hidden = true;
  }, timeout);
}

/* -------------------------------------------------------------------------- */
/* Data loading                                                               */
/* -------------------------------------------------------------------------- */

async function loadData() {
  setLoadingState();

  try {
    const response = await fetch(`./data.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    validateData(data);
    state.data = data;
    renderAll();
  } catch (error) {
    console.error("读取 data.json 失败", error);
    showLoadError(error);
  }
}

function validateData(data) {
  if (!data || typeof data !== "object") throw new Error("data.json 格式不正确");
  if (!Array.isArray(data.funds) || data.funds.length === 0) {
    throw new Error("data.json 缺少 funds");
  }
  if (!Array.isArray(data.dates)) throw new Error("data.json 缺少 dates");
  if (!data.series || typeof data.series !== "object") {
    throw new Error("data.json 缺少 series");
  }

  for (const fund of data.funds) {
    if (!fund || typeof fund.code !== "string") throw new Error("基金配置缺少代码");
    const series = data.series[fund.code];
    if (!series) throw new Error(`${fund.code} 缺少序列`);
    for (const key of ["shares", "nav", "net_subscription", "market_value"]) {
      if (!Array.isArray(series[key])) throw new Error(`${fund.code} 缺少 ${key}`);
      if (series[key].length !== data.dates.length) {
        throw new Error(`${fund.code} 的 ${key} 与日期长度不一致`);
      }
    }
  }

  if (data.market && !Array.isArray(data.market.distribution)) {
    throw new Error("market.distribution 格式不正确");
  }
}

function setLoadingState() {
  const status = $(".market-status");
  status.className = "market-status";
  $("#statusText").textContent = "读取中";
  $("#statusDate").textContent = "—";
  $("#marketNote").className = "market-note";
  $("#marketNote").textContent = "正在读取全市场行情";
  for (const id of ["upCount", "flatCount", "downCount", "totalCount", "limitUp", "limitDown"]) {
    $(`#${id}`).textContent = "—";
  }
  $("#turnover").textContent = "—";
  $("#turnoverBreakdown").textContent = "";
  $("#demoBadge").hidden = true;
  $("#footerMeta").textContent = "仅供个人复盘，不构成投资建议";
}

/* -------------------------------------------------------------------------- */
/* Rendering                                                                  */
/* -------------------------------------------------------------------------- */

function renderAll() {
  renderStatus();
  renderMarket();
  renderCharts();
}

function renderStatus() {
  const { meta = {}, market, demo = false, dates = [] } = state.data;
  const marketStale = !market || Boolean(market.is_stale);
  const stale = Boolean(meta.is_stale) || marketStale;
  const hasData = dates.length > 0;

  const status = $(".market-status");
  status.className = `market-status ${stale ? "is-stale" : hasData ? "is-ok" : "is-error"}`;
  $("#statusText").textContent = stale ? (market ? "待补跑" : "部分缺失") : "已更新";
  $("#statusDate").textContent = formatDateDot(meta.data_date || market?.date);

  $("#demoBadge").hidden = !demo;

  const note = $("#marketNote");
  note.className = "market-note";
  if (demo) {
    note.textContent = "演示数据 · 首次 GitHub Actions 运行后替换为真实行情";
  } else if (stale) {
    const reasons = [];
    if (meta.is_stale && meta.stale_reason) reasons.push(meta.stale_reason);
    if (!market) reasons.push("当日全市场行情暂不可用");
    else if (market.is_stale && market.stale_reason) reasons.push(market.stale_reason);
    note.textContent = reasons.join("；") || "最新交易日数据尚未完整发布";
    note.classList.add("is-warn");
  } else if (market) {
    note.textContent = `全市场 ${formatInteger(market.total)} 只个股 · 数据时间 ${formatDateTime(market.as_of || meta.generated_at)}`;
  } else {
    note.textContent = "大盘行情暂缺";
    note.classList.add("is-warn");
  }

  $("#footerMeta").textContent = meta.generated_at
    ? `仅供个人复盘，不构成投资建议 · 生成于 ${formatDateTime(meta.generated_at)}`
    : "仅供个人复盘，不构成投资建议";
}

function renderMarket() {
  const market = state.data.market;
  if (!market) {
    for (const id of ["upCount", "flatCount", "downCount", "totalCount", "limitUp", "limitDown"]) {
      $(`#${id}`).textContent = "—";
    }
    $("#turnover").textContent = "—";
    $("#turnoverBreakdown").textContent = "";
    return;
  }

  $("#upCount").textContent = formatInteger(market.up);
  $("#flatCount").textContent = formatInteger(market.flat);
  $("#downCount").textContent = formatInteger(market.down);
  $("#totalCount").textContent = formatInteger(market.total);
  $("#limitUp").textContent = formatInteger(market.limit_up);
  $("#limitDown").textContent = formatInteger(market.limit_down);
  $("#turnover").textContent = formatTurnover(market.turnover);

  const parts = [];
  if (Number.isFinite(Number(market.turnover_sh))) parts.push(`沪 ${formatTurnoverPart(market.turnover_sh)}`);
  if (Number.isFinite(Number(market.turnover_sz))) parts.push(`深 ${formatTurnoverPart(market.turnover_sz)}`);
  if (Number.isFinite(Number(market.turnover_bj))) parts.push(`北 ${formatTurnoverPart(market.turnover_bj)}`);
  $("#turnoverBreakdown").textContent = parts.join(" · ");
}

/* -------------------------------------------------------------------------- */
/* Charts                                                                     */
/* -------------------------------------------------------------------------- */

async function ensureChartLibrary() {
  if (window.Chart) return true;
  if (state.chartLoader) return state.chartLoader;

  state.chartLoader = (async () => {
    const sources = [
      "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js",
      "https://unpkg.com/chart.js@4.4.7/dist/chart.umd.min.js",
    ];
    for (const source of sources) {
      const loaded = await loadScriptWithTimeout(source, 3500);
      if (loaded && window.Chart) return true;
    }
    return false;
  })();

  return state.chartLoader;
}

function loadScriptWithTimeout(source, timeout) {
  return new Promise((resolve) => {
    const script = document.createElement("script");
    let settled = false;

    const finish = (result) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      if (!result) script.remove();
      resolve(result);
    };

    const timer = window.setTimeout(() => finish(false), timeout);
    script.src = source;
    script.async = true;
    script.onload = () => finish(Boolean(window.Chart));
    script.onerror = () => finish(false);
    document.head.appendChild(script);
  });
}

function chartColors() {
  return {
    text: cssValue("--text") || "#111318",
    muted: cssValue("--muted") || "#7a8494",
    grid: matchMedia("(prefers-color-scheme: dark)").matches
      ? "rgba(226,232,240,0.09)"
      : "rgba(17,19,24,0.07)",
    zero: matchMedia("(prefers-color-scheme: dark)").matches
      ? "rgba(226,232,240,0.24)"
      : "rgba(17,19,24,0.2)",
    tooltip: matchMedia("(prefers-color-scheme: dark)").matches
      ? "rgba(18,20,24,0.97)"
      : "rgba(17,19,24,0.96)",
  };
}

async function renderCharts() {
  if (!state.data) return;

  if (!window.Chart) {
    setChartEmpty("breadthChart", "图表加载中…", "正在加载 Chart.js；网络不可用时会切换兼容渲染。");
    if (state.data.dates.length) {
      setChartEmpty("netChart", "图表加载中…", "正在加载 Chart.js；网络不可用时会切换兼容渲染。");
      setChartEmpty("scaleChart", "图表加载中…", "正在加载 Chart.js；网络不可用时会切换兼容渲染。");
    }
  }

  const available = await ensureChartLibrary();
  if (!available) {
    renderFallbackCharts();
    return;
  }

  try {
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = chartColors().muted;
    renderBreadthChart();
    renderEtfCharts();
    document.body.dataset.chartRenderer = "chartjs";
  } catch (error) {
    console.warn("Chart.js 渲染失败，切换到兼容渲染", error);
    state.charts.breadth?.destroy();
    state.charts.net?.destroy();
    state.charts.scale?.destroy();
    renderFallbackCharts();
  }
}

function breadthColor(index) {
  return [
    "#b42318",
    "#d92d20",
    "#f04438",
    "#f97066",
    "#75e0a7",
    "#32d583",
    "#12b76a",
    "#027a48",
  ][index] || "#98a2b3";
}

function renderBreadthChart() {
  const market = state.data.market;
  if (!market || !market.distribution.length) {
    state.charts.breadth?.destroy();
    state.charts.breadth = null;
    setChartEmpty("breadthChart", "暂无大盘数据", "等待当天全市场行情更新。");
    return;
  }

  clearChartEmpty("breadthChart");
  state.charts.breadth?.destroy();
  const colors = chartColors();
  const distribution = market.distribution;

  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.color = colors.muted;

  state.charts.breadth = new Chart($("#breadthChart").getContext("2d"), {
    type: "bar",
    data: {
      labels: distribution.map((item) => item.label.replace("%", "")),
      datasets: [{
        data: distribution.map((item) => item.count),
        backgroundColor: distribution.map((item, index) => breadthColor(index)),
        borderRadius: 3,
        borderSkipped: false,
        minBarLength: 2,
        barPercentage: 0.72,
        categoryPercentage: 0.82,
      }],
    },
    options: breadthOptions(colors, distribution),
    plugins: [barValuePlugin(colors)],
  });
}

function breadthOptions(colors, distribution) {
  const narrow = window.innerWidth < 380;
  const rotation = narrow ? 45 : 0;

  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    layout: { padding: { top: 17, right: 8, bottom: 0, left: 0 } },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: colors.tooltip,
        titleColor: "#ffffff",
        bodyColor: "#e2e8f0",
        borderColor: "rgba(255,255,255,0.14)",
        borderWidth: 1,
        padding: 9,
        cornerRadius: 8,
        displayColors: false,
        callbacks: {
          title: (items) => distribution[items[0]?.dataIndex]?.label || "",
          label: (context) => `${formatInteger(context.parsed.y)} 家`,
        },
      },
    },
    scales: {
      x: {
        offset: true,
        grid: { display: false },
        border: { display: false },
        ticks: {
          color: colors.muted,
          minRotation: rotation,
          maxRotation: rotation,
          autoSkip: false,
          font: { size: 9, weight: "500" },
        },
      },
      y: {
        beginAtZero: true,
        grid: { color: colors.grid, drawTicks: false },
        border: { display: false },
        ticks: {
          color: colors.muted,
          padding: 6,
          precision: 0,
          maxTicksLimit: 4,
          font: { size: 9, weight: "500" },
        },
      },
    },
  };
}

function barValuePlugin(colors) {
  return {
    id: "barValue",
    afterDatasetsDraw(chart) {
      const { ctx } = chart;
      const dataset = chart.data.datasets[0];
      const meta = chart.getDatasetMeta(0);
      ctx.save();
      ctx.fillStyle = colors.muted;
      ctx.font = `9px ${getComputedStyle(document.body).fontFamily}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      meta.data.forEach((bar, index) => {
        const value = dataset.data[index];
        if (!value) return;
        ctx.fillText(formatInteger(value), bar.x, bar.y - 4);
      });
      ctx.restore();
    },
  };
}

function renderEtfCharts() {
  if (!state.data.dates.length) {
    state.charts.net?.destroy();
    state.charts.scale?.destroy();
    state.charts.net = null;
    state.charts.scale = null;
    setChartEmpty("netChart", "暂无净申购数据", "抓取脚本生成 data.json 后显示。");
    setChartEmpty("scaleChart", "暂无总市值数据", "抓取脚本生成 data.json 后显示。");
    return;
  }

  const slice = visibleSlice();
  if (!slice.dates.length) return;
  const colors = chartColors();

  clearChartEmpty("netChart");
  clearChartEmpty("scaleChart");
  state.charts.net?.destroy();
  state.charts.scale?.destroy();

  state.charts.net = new Chart($("#netChart").getContext("2d"), {
    type: "line",
    data: {
      labels: slice.dates.map(formatShortDate),
      datasets: slice.funds.map((fund) => ({
        label: fund.short_name,
        code: fund.code,
        data: slice.series[fund.code].net_subscription,
        borderColor: fund.color,
        backgroundColor: fund.color,
        borderWidth: 1.8,
        pointRadius: 0,
        pointHoverRadius: 3.5,
        pointHitRadius: 12,
        tension: 0.28,
        spanGaps: false,
      })),
    },
    options: etfOptions(colors, slice.dates, "net"),
    plugins: [zeroLinePlugin(colors.zero)],
  });

  state.charts.scale = new Chart($("#scaleChart").getContext("2d"), {
    type: "line",
    data: {
      labels: slice.dates.map(formatShortDate),
      datasets: slice.funds.map((fund) => ({
        label: fund.short_name,
        code: fund.code,
        data: slice.series[fund.code].market_value,
        borderColor: fund.color,
        backgroundColor: fund.color,
        borderWidth: 1.8,
        pointRadius: 0,
        pointHoverRadius: 3.5,
        pointHitRadius: 12,
        tension: 0.28,
        spanGaps: false,
      })),
    },
    options: etfOptions(colors, slice.dates, "scale"),
  });
}

function etfOptions(colors, dates, mode) {
  const isNet = mode === "net";
  const compact = window.innerWidth < 520;
  const xTickLimit = compact ? 4 : 7;
  const yTickLimit = compact ? 4 : 6;

  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    animation: false,
    layout: { padding: { top: 7, right: 14, bottom: 0, left: 0 } },
    plugins: {
      legend: {
        position: "bottom",
        align: "start",
        labels: {
          color: colors.muted,
          usePointStyle: true,
          pointStyle: "circle",
          boxWidth: 6,
          boxHeight: 6,
          padding: 12,
          font: { size: 10, weight: "500" },
        },
      },
      tooltip: {
        backgroundColor: colors.tooltip,
        titleColor: "#ffffff",
        bodyColor: "#e2e8f0",
        borderColor: "rgba(255,255,255,0.14)",
        borderWidth: 1,
        padding: 9,
        cornerRadius: 8,
        displayColors: true,
        boxWidth: 6,
        boxHeight: 6,
        usePointStyle: true,
        callbacks: {
          title: (items) => {
            const index = items[0]?.dataIndex;
            return index === undefined ? "" : formatChineseDate(dates[index]);
          },
          label: (context) => {
            const value = context.parsed.y;
            const formatted = isNet ? `${formatSigned(value)} 亿元` : `${formatNumber(value)} 亿元`;
            return ` ${context.dataset.label}${context.dataset.code ? ` ${context.dataset.code}` : ""}  ${formatted}`;
          },
        },
      },
    },
    scales: {
      x: {
        grid: { display: false },
        border: { display: false },
        ticks: {
          color: colors.muted,
          maxRotation: 0,
          autoSkip: false,
          font: { size: 9.5, weight: "500" },
          callback: (value, index) => {
            const total = dates.length;
            if (total <= xTickLimit) return formatShortDate(dates[index]);
            if (index === 0 || index === total - 1) return formatShortDate(dates[index]);
            const step = Math.max(1, Math.ceil((total - 1) / (xTickLimit - 1)));
            return index % step === 0 ? formatShortDate(dates[index]) : "";
          },
        },
      },
      y: {
        grid: { color: colors.grid, drawTicks: false },
        border: { display: false },
        ticks: {
          color: colors.muted,
          padding: 7,
          maxTicksLimit: yTickLimit,
          font: { size: 9.5, weight: "500" },
          callback: (value) => (isNet && value > 0 ? `+${formatAxis(value)}` : formatAxis(value)),
        },
      },
    },
  };
}

function zeroLinePlugin(color) {
  return {
    id: "zeroLine",
    beforeDatasetsDraw(chart) {
      const { ctx, chartArea, scales } = chart;
      if (!chartArea || !scales.y) return;
      const y = scales.y.getPixelForValue(0);
      if (!Number.isFinite(y) || y < chartArea.top || y > chartArea.bottom) return;
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(chartArea.left, y);
      ctx.lineTo(chartArea.right, y);
      ctx.stroke();
      ctx.restore();
    },
  };
}

function visibleSlice() {
  const { dates, series, funds } = state.data;
  const count = Math.min(state.range, dates.length);
  const start = Math.max(0, dates.length - count);
  return {
    dates: dates.slice(start),
    funds,
    series: Object.fromEntries(
      funds.map((fund) => {
        const fundSeries = series[fund.code];
        return [fund.code, {
          net_subscription: fundSeries.net_subscription.slice(start),
          market_value: fundSeries.market_value.slice(start),
        }];
      }),
    ),
  };
}

/* -------------------------------------------------------------------------- */
/* Fallback canvas renderer                                                   */
/* -------------------------------------------------------------------------- */

function renderFallbackCharts() {
  document.body.dataset.chartRenderer = "fallback";
  const colors = chartColors();

  if (state.data.market?.distribution?.length) {
    drawFallbackBreadthChart($("#breadthChart"), state.data.market, colors);
    clearChartEmpty("breadthChart");
  } else {
    setChartEmpty("breadthChart", "暂无大盘数据", "等待当天全市场行情更新。");
  }

  if (!state.data.dates.length) {
    setChartEmpty("netChart", "暂无净申购数据", "抓取脚本生成 data.json 后显示。");
    setChartEmpty("scaleChart", "暂无总市值数据", "抓取脚本生成 data.json 后显示。");
    return;
  }

  const slice = visibleSlice();
  drawFallbackLineChart($("#netChart"), {
    dates: slice.dates,
    datasets: slice.funds.map((fund) => ({
      label: fund.short_name,
      color: fund.color,
      values: slice.series[fund.code].net_subscription,
    })),
    mode: "net",
    colors,
  });
  drawFallbackLineChart($("#scaleChart"), {
    dates: slice.dates,
    datasets: slice.funds.map((fund) => ({
      label: fund.short_name,
      color: fund.color,
      values: slice.series[fund.code].market_value,
    })),
    mode: "scale",
    colors,
  });
  clearChartEmpty("netChart");
  clearChartEmpty("scaleChart");
}

function drawFallbackBreadthChart(canvas, market, colors) {
  if (!canvas) return;
  const wrap = canvas.parentElement;
  const width = Math.max(260, wrap.clientWidth || 320);
  const height = Math.max(190, wrap.clientHeight || 210);
  const dpr = Math.min(window.devicePixelRatio || 1, 2);

  canvas.hidden = false;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  canvas.style.width = "100%";
  canvas.style.height = "100%";

  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const distribution = market.distribution;
  const compact = width < 380;
  const left = 30;
  const right = 6;
  const top = 18;
  const bottom = compact ? 48 : 32;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const rawMax = Math.max(...distribution.map((item) => item.count), 1);
  const magnitude = 10 ** Math.floor(Math.log10(rawMax));
  const max = Math.ceil(rawMax / magnitude) * magnitude;
  const slot = plotWidth / distribution.length;
  const barWidth = Math.min(26, slot * 0.58);

  ctx.font = `9px ${getComputedStyle(document.body).fontFamily}`;
  ctx.textBaseline = "middle";

  for (let tick = 0; tick <= 3; tick += 1) {
    const value = (max / 3) * tick;
    const y = top + plotHeight - (value / max) * plotHeight;
    ctx.strokeStyle = colors.grid;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(width - right, y);
    ctx.stroke();
    ctx.fillStyle = colors.muted;
    ctx.textAlign = "right";
    ctx.fillText(formatAxis(Math.round(value)), left - 5, y);
  }

  distribution.forEach((item, index) => {
    const x = left + slot * index + slot / 2;
    const barHeight = Math.max(2, (item.count / max) * plotHeight);
    const y = top + plotHeight - barHeight;
    ctx.fillStyle = breadthColor(index);
    const radius = Math.min(3, barWidth / 3);
    if (typeof ctx.roundRect === "function") {
      ctx.beginPath();
      ctx.roundRect(x - barWidth / 2, y, barWidth, barHeight, radius);
      ctx.fill();
    } else {
      ctx.fillRect(x - barWidth / 2, y, barWidth, barHeight);
    }

    if (item.count) {
      ctx.fillStyle = colors.muted;
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      ctx.fillText(formatInteger(item.count), x, y - 3);
    }

    ctx.fillStyle = colors.muted;
    if (compact) {
      ctx.save();
      ctx.translate(x, top + plotHeight + 6);
      ctx.rotate(-Math.PI / 4);
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(item.label.replace("%", ""), 0, 0);
      ctx.restore();
    } else {
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(item.label.replace("%", ""), x, top + plotHeight + 8);
    }
  });

  ctx.textBaseline = "middle";
}

function drawFallbackLineChart(canvas, config) {
  if (!canvas) return;
  const wrap = canvas.parentElement;
  const width = Math.max(260, wrap.clientWidth || 320);
  const height = Math.max(240, wrap.clientHeight || 300);
  const dpr = Math.min(window.devicePixelRatio || 1, 2);

  canvas.hidden = false;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  canvas.style.width = "100%";
  canvas.style.height = "100%";

  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const { colors, mode, dates, datasets } = config;
  const isNet = mode === "net";
  const compact = width < 430;
  const left = compact ? 37 : 45;
  const right = 8;
  const top = 14;
  const bottom = compact ? 48 : 42;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  if (plotWidth <= 10 || plotHeight <= 10) return;

  const values = datasets.flatMap((dataset) => dataset.values).filter((value) => Number.isFinite(value));
  if (isNet) values.push(0);
  if (!values.length) return;

  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const padding = Math.max((max - min) * 0.12, isNet ? 1 : 2);
  min -= padding;
  max += padding;

  const xFor = (index) => left + (dates.length <= 1 ? plotWidth / 2 : (index / (dates.length - 1)) * plotWidth);
  const yFor = (value) => top + ((max - value) / (max - min)) * plotHeight;

  ctx.font = `9px ${getComputedStyle(document.body).fontFamily}`;
  ctx.textBaseline = "middle";

  const tickCount = compact ? 4 : 5;
  for (let index = 0; index < tickCount; index += 1) {
    const ratio = index / (tickCount - 1);
    const value = max - ratio * (max - min);
    const y = top + ratio * plotHeight;
    ctx.strokeStyle = colors.grid;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(width - right, y);
    ctx.stroke();
    ctx.fillStyle = colors.muted;
    ctx.textAlign = "right";
    ctx.fillText(isNet && value > 0 ? `+${formatAxis(value)}` : formatAxis(value), left - 5, y);
  }

  if (isNet) {
    ctx.strokeStyle = colors.zero;
    ctx.setLineDash([4, 4]);
    const zeroY = yFor(0);
    if (zeroY >= top && zeroY <= top + plotHeight) {
      ctx.beginPath();
      ctx.moveTo(left, zeroY);
      ctx.lineTo(width - right, zeroY);
      ctx.stroke();
    }
    ctx.setLineDash([]);
  }

  const tickTotal = Math.min(compact ? 4 : 6, dates.length);
  const tickIndices = [];
  for (let index = 0; index < tickTotal; index += 1) {
    tickIndices.push(Math.round((index / Math.max(1, tickTotal - 1)) * (dates.length - 1)));
  }
  ctx.fillStyle = colors.muted;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (const index of [...new Set(tickIndices)]) {
    ctx.fillText(formatShortDate(dates[index]), xFor(index), top + plotHeight + 7);
  }

  for (const dataset of datasets) {
    ctx.strokeStyle = dataset.color;
    ctx.lineWidth = 1.8;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.beginPath();
    let started = false;
    dataset.values.forEach((value, index) => {
      if (!Number.isFinite(value)) {
        started = false;
        return;
      }
      const x = xFor(index);
      const y = yFor(value);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.stroke();

    const lastIndex = findLastIndex(dataset.values, (value) => Number.isFinite(value));
    if (lastIndex >= 0) {
      ctx.fillStyle = dataset.color;
      ctx.beginPath();
      ctx.arc(xFor(lastIndex), yFor(dataset.values[lastIndex]), 2.4, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  const legendY = height - 14;
  let legendX = left;
  for (const dataset of datasets) {
    const textWidth = ctx.measureText(dataset.label).width;
    const itemWidth = textWidth + 18;
    if (legendX + itemWidth > width - right) legendX = left;
    ctx.fillStyle = dataset.color;
    ctx.beginPath();
    ctx.arc(legendX + 3, legendY, 2.6, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = colors.muted;
    ctx.fillText(dataset.label, legendX + 10, legendY);
    legendX += itemWidth;
  }
}

/* -------------------------------------------------------------------------- */
/* Empty states and errors                                                    */
/* -------------------------------------------------------------------------- */

function setChartEmpty(canvasId, title, message) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const wrap = canvas.parentElement;
  canvas.hidden = true;
  let empty = wrap.querySelector(".chart-empty");
  if (!empty) {
    empty = document.createElement("div");
    empty.className = "chart-empty";
    wrap.appendChild(empty);
  }
  empty.innerHTML = `<div><strong>${escapeHtml(title)}</strong><p>${escapeHtml(message)}</p></div>`;
}

function clearChartEmpty(canvasId) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const wrap = canvas.parentElement;
  canvas.hidden = false;
  wrap.querySelector(".chart-empty")?.remove();
}

function showLoadError(error) {
  const status = $(".market-status");
  status.className = "market-status is-error";
  $("#statusText").textContent = "读取失败";
  $("#statusDate").textContent = "—";
  $("#demoBadge").hidden = true;
  $("#marketNote").className = "market-note is-error";
  $("#marketNote").textContent = `无法读取 data.json：${error?.message || "未知错误"}。请确认文件已部署到 Pages 根目录。`;

  for (const id of ["upCount", "flatCount", "downCount", "totalCount", "limitUp", "limitDown"]) {
    $(`#${id}`).textContent = "—";
  }
  $("#turnover").textContent = "—";
  $("#turnoverBreakdown").textContent = "";

  setChartEmpty("breadthChart", "暂无大盘数据", "data.json 读取失败，修复后刷新页面。");
  setChartEmpty("netChart", "暂无图表", "data.json 读取失败，修复后刷新页面。");
  setChartEmpty("scaleChart", "暂无图表", "data.json 读取失败，修复后刷新页面。");
}

/* -------------------------------------------------------------------------- */
/* Controls, PWA and init                                                     */
/* -------------------------------------------------------------------------- */

function updateRangeButtons() {
  $$("#rangeSwitch button").forEach((button) => {
    const active = Number(button.dataset.range) === state.range;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function bindRangeControls() {
  $$("#rangeSwitch button").forEach((button) => {
    button.addEventListener("click", () => {
      const range = Number(button.dataset.range);
      if (![30, 90, 180].includes(range)) return;
      state.range = range;
      try {
        localStorage.setItem("shunwei-range", String(range));
      } catch (error) {
        // 忽略隐私模式下的 localStorage 错误。
      }
      updateRangeButtons();
      if (state.data) renderCharts();
    });
  });
}

function bindInstallPrompt() {
  const installButton = $("#installBtn");
  let deferredPrompt = null;

  const standalone = () =>
    window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);

  if (standalone()) {
    installButton.hidden = true;
  } else if (isIos) {
    installButton.hidden = false;
  }

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event;
    installButton.hidden = false;
  });

  installButton.addEventListener("click", async () => {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      try {
        await deferredPrompt.userChoice;
      } finally {
        deferredPrompt = null;
        installButton.hidden = true;
      }
      return;
    }
    showToast("iPhone/iPad：点击 Safari 分享按钮，再选择“添加到主屏幕”。", 4600);
  });

  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    installButton.hidden = true;
    showToast("已添加到桌面。");
  });
}

function bindNetworkStatus() {
  window.addEventListener("offline", () => showToast("当前处于离线状态，显示最近缓存数据。"));
  window.addEventListener("online", () => {
    showToast("网络已恢复。");
    if (!state.data) loadData();
  });
}

function registerServiceWorker() {
  if (!("serviceWorker" in navigator) || !location.protocol.startsWith("http")) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("./sw.js", { scope: "./", updateViaCache: "none" })
      .catch((error) => console.warn("Service Worker 注册失败", error));
  });
}

function debounce(callback, delay) {
  let timer = null;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => callback(...args), delay);
  };
}

function init() {
  bindRangeControls();
  bindInstallPrompt();
  bindNetworkStatus();
  registerServiceWorker();
  updateRangeButtons();
  loadData();

  const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
  if (typeof darkQuery.addEventListener === "function") {
    darkQuery.addEventListener("change", () => {
      if (state.data) renderCharts();
    });
  }

  window.addEventListener(
    "resize",
    debounce(() => {
      if (state.data) renderCharts();
    }, 180),
  );
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
