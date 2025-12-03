(() => {
  
  console.log("Starting Javascript")
  const dataEl = document.getElementById("dashboard-data-inline");
  const parseInlineData = () => {
    if (!dataEl) {
      return null;
    }
    try {
      return JSON.parse(dataEl.textContent || "");
    } catch (warning) {
      console.warn("Failed to parse inline dashboard data; falling back to fetch.", warning);
      return null;
    }
  };

  let dashboardData = parseInlineData() || {};
  let currentArchiveSlug = dashboardData.generatedDateSlug || "";
  const scriptEl = document.getElementById("dashboard-client");
  const archivePathRaw = scriptEl?.dataset.archivePath || "chart hist";
  const archivePathHref = encodeURI(archivePathRaw);
  const buildArchiveJsonUrl = (slug) =>
    slug ? `${archivePathHref}/${slug}.json?v=${Date.now()}` : null;
  const logEl = document.getElementById("js-log");
  const logMessage = (message, level = "log") => {
    if (logEl) {
      logEl.style.display = "block";
      logEl.textContent += `${message}\n`;
      logEl.scrollTop = logEl.scrollHeight;
    }
    console[level](message);
  };

  const chartHistoryList = document.getElementById("chart-history-list");
  const chartHistoryToggle = document.getElementById("chart-history-toggle");
  const chartHistoryStatus = document.getElementById("chart-history-status");
  const archiveLabelMap = new Map();
  const chartControlButtons = document.querySelectorAll(".chart-control");
  const canvas = document.getElementById("history-chart");
  const ctx = canvas ? canvas.getContext("2d") : null;
  const toggleHistoryBtn = document.getElementById("toggle-history");
  const handsLogoTop = document.querySelector(".hands-logo-top");
  const timestampDisplay = document.getElementById("dashboard-timestamp");
  let chart = null;
  let cardsInitialized = false;

  const getDashboardData = () => dashboardData || {};
  const getDashboardValue = (key, fallback) => getDashboardData()[key] || fallback;
  const getChartLabels = () => getDashboardValue("chartLabels", []);
  const getSetpointSeries = () => getDashboardValue("setpoint", []);
  const getActualSeries = () => getDashboardValue("actual", []);
  const getOutsideSeries = () => getDashboardValue("outside", []);
  const getFanSeries = () => getDashboardValue("fan", []);
  const getCoolingSeries = () => getDashboardValue("cooling", []);
  const getOutsideFlags = () => getDashboardValue("outsideFlags", []);
  const getOutsideFlagDayChars = () => getDashboardValue("outsideFlagDayChars", []);
  const getSetpointLabel = () => getDashboardData().setpointLabel || "Target Temperature";
  const getActualLabel = () => getDashboardData().actualLabel || "Building Temperature";
  const getOutsideLabel = () => getDashboardData().outsideLabel || "Outside Temp";
  const getCoolingLabel = () => getDashboardData().coolingLabel || "Cooling Status";
  const getFanLegend = () => getDashboardValue("fanLegend", ["On", "Circulate", "Auto"]);
  const getCoolingLegend = () => getDashboardValue("coolingLegend", ["Idle", "Cooling"]);
  const getCondenserMinutes = () => getDashboardValue("condenserMinutes", []);

  const fanStateLabels = {
    A: "Auto",
    C: "Circulate",
    O: "On",
  };
  const fanStateToNumeric = {
    A: 0,
    C: 1,
    O: 2,
  };
  const normalizeFanState = (value) => {
    if (typeof value === "string") {
      return value.trim().toUpperCase();
    }
    if (typeof value === "number" && Number.isFinite(value)) {
      if (value === 1) {
        return "C";
      }
      if (value === 2) {
        return "O";
      }
    }
    return "A";
  };
  const fanLabelForValue = (value) => {
    const normalized = normalizeFanState(value);
    return fanStateLabels[normalized] || String(value);
  };
  const findLastNumber = (arr) => {
    if (!arr) {
      return undefined;
    }
    for (let idx = arr.length - 1; idx >= 0; idx -= 1) {
      const value = arr[idx];
      if (typeof value === "number" && !Number.isNaN(value)) {
        return value;
      }
    }
    return undefined;
  };
  const getFanSeriesNumeric = () =>
    getFanSeries().map((value) => fanStateToNumeric[normalizeFanState(value)] ?? 0);
  const getLatestActualValue = () =>
    getDashboardData().latestActual ?? findLastNumber(getActualSeries()) ?? 50;
  const getLatestSetpointValue = () =>
    getDashboardData().latestSetpoint ?? findLastNumber(getSetpointSeries()) ?? 50;
  const getLatestOutsideValue = () =>
    getDashboardData().latestOutside ?? findLastNumber(getOutsideSeries()) ?? 50;
  const getLatestOutsideRaw = () => (getDashboardData().latestOutsideRaw || "").trim().toUpperCase();
  const getOutsideFlag = () => {
    const raw = getLatestOutsideRaw();
    return raw ? raw.charAt(0) : "";
  };
  const getOutsideFlagDayChar = () => {
    const raw = getLatestOutsideRaw();
    return raw && raw.length > 1 ? raw.charAt(1) : "D";
  };
  const getOutsideDaylight = () =>
    typeof getDashboardData().latestOutsideDaylight === "boolean"
      ? getDashboardData().latestOutsideDaylight
      : getOutsideFlagDayChar() !== "N";
  const getLatestFanRaw = () => getDashboardData().latestFan;
  const getLatestFanValue = () =>
    fanStateToNumeric[normalizeFanState(getLatestFanRaw())] ??
    findLastNumber(getFanSeriesNumeric()) ??
    0;
  const getLatestCoolingValue = () =>
    getDashboardData().latestCooling ?? findLastNumber(getCoolingSeries()) ?? 0;
  const getLatestCondenserState = () =>
    (getDashboardData().latestCondenserState || "").trim();
  const formatMinutesValue = (value) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return null;
    }
    const numeric = Number(value);
    if (Number.isInteger(numeric)) {
      return `${numeric} min`;
    }
    return `${numeric.toFixed(1)} min`;
  };
  const gradientColorFor = (value) => {
    if (typeof value !== "number" || Number.isNaN(value)) {
      return "#999";
    }
    const ratio = Math.max(0, Math.min((value - 45) / 55, 1));
    const start = [50, 130, 255];
    const end = [255, 40, 40];
    const rgb = start.map((component, idx) =>
      Math.round(component + (end[idx] - component) * ratio)
    );
    return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
  };
  const colorForPoint = (value) => gradientColorFor(value ?? 50);
  const gradientColorForOutside = (value) => {
    const numeric = typeof value === "number" ? value : parseFloat(value);
    const clamped = Number.isNaN(numeric) ? 50 : Math.max(45, Math.min(numeric, 100));
    const ratio = Math.max(0, Math.min((clamped - 45) / 55, 1));
    const start = [0, 0, 0];
    const end = [255, 214, 0];
    const rgb = start.map((component, idx) =>
      Math.round(component + (end[idx] - component) * ratio)
    );
    return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
  };
  const getContrastColor = (color) => {
    const match = color && color.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (!match) {
      return "#f5f7ff";
    }
    const [, r, g, b] = match;
    const brightness = (Number(r) * 299 + Number(g) * 587 + Number(b) * 114) / 1000;
    return brightness > 186 ? "#000" : "#fff";
  };
  const applyCardColor = (card, color, forcedTextColor = null, setBackground = true) => {
    if (!card || !color) {
      return;
    }
    if (setBackground) {
      card.style.background = color;
      card.style.borderColor = color;
    } else {
      card.style.background = "transparent";
      card.style.borderColor = "transparent";
    }
    const textColor = forcedTextColor || getContrastColor(color);
    card.style.color = textColor;
    const labelEl = card.querySelector(".label");
    if (labelEl) {
      labelEl.style.color = textColor;
    }
    const valueEl = card.querySelector(".value");
    if (valueEl) {
      valueEl.style.color = textColor;
    }
  };
  const setCardValue = (card, text) => {
    if (!card) {
      return;
    }
    const valueEl = card.querySelector(".value");
    if (valueEl) {
      valueEl.textContent = text;
    }
  };
  const formatTemperatureValue = (value) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return "";
    }
    const numeric = Number(value);
    if (Number.isInteger(numeric)) {
      return String(Math.round(numeric));
    }
    return numeric.toFixed(1);
  };
  const formatOutsideDisplay = (value) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return "";
    }
    const numeric = Number(value);
    if (Number.isInteger(numeric)) {
      return String(Math.round(numeric));
    }
    return numeric.toFixed(1);
  };

  const outsideFlagColors = {
    S: "#ffd000",
    P: "#ffb347",
    O: "#b4b4b4",
    R: "#5da9f7",
    N: "#0b1b3a",
  };
  const weatherGraphicPaths = {
    S: "../../../Images/sunny.png",
    "P-day": "../../../Images/PartlySunny.png",
    "P-night": "../../../Images/Night.png",
    "O-day": "../../../Images/cloudy.png",
    "O-night": "../../../Images/cloudynight.png",
    "R-day": "../../../Images/RainyDay.png",
    "R-night": "../../../Images/RainyNight.png",
    N: "../../../Images/clearnight.png",
  };
  const weatherGraphicImages = {};
  Object.entries(weatherGraphicPaths).forEach(([key, src]) => {
    const img = new Image();
    img.src = src;
    weatherGraphicImages[key] = img;
  });
  const getWeatherGraphicKey = (flag, dayChar) => {
    const normalizedFlag = (flag || "").toUpperCase();
    const normalizedDayChar = (dayChar || "D").toUpperCase();
    const isNight = normalizedDayChar === "N" || normalizedDayChar === "M";
    const isDay = !isNight;
    if (normalizedFlag === "P") {
      return isDay ? "P-day" : "P-night";
    }
    if (normalizedFlag === "O") {
      return isDay ? "O-day" : "O-night";
    }
    if (normalizedFlag === "R") {
      return isDay ? "R-day" : "R-night";
    }
    if (normalizedFlag === "N") {
      return "N";
    }
    return "S";
  };

  const fanStyleMap = {
    auto: {
      background: "#b4b4b4",
      border: "#8c8c8c",
      text: "#1a1a1a",
    },
    circulate: {
      background: "radial-gradient(circle at 50% 40%, #ffd54f 0%, #f0a500 40%, #c2923a 100%)",
      border: "#c47f00",
      text: "#2d1e00",
    },
    on: {
      background: "#059c15",
      border: "#03660d",
      text: "#ffffff",
    },
  };
  const fanStateMap = {
    0: "auto",
    1: "circulate",
    2: "on",
  };
  const applyFanCardStyle = (card, fanValue) => {
    if (!card) {
      return;
    }
    const state = fanStateMap[fanValue] || "auto";
    const style = fanStyleMap[state];
    if (!style) {
      return;
    }
    card.style.background = style.background;
    card.style.borderColor = style.border;
    card.style.color = style.text;
    const labelEl = card.querySelector(".label");
    if (labelEl) {
      labelEl.style.color = style.text;
    }
    const valueEl = card.querySelector(".value");
    if (valueEl) {
      valueEl.style.color = style.text;
    }
  };

  const coolingStyleMap = {
    idle: {
      background: "#e0e2e5",
      border: "#b0b4ba",
      text: "#1a1a1a",
    },
    cooling: {
      background: "#059c15",
      border: "#03660d",
      text: "#ffffff",
    },
  };
  const coolingStateMap = {
    0: "idle",
    1: "cooling",
  };
  const applyCoolingCardStyle = (card, coolingValue) => {
    if (!card) {
      return;
    }
    const state = coolingStateMap[coolingValue] || "idle";
    const style = coolingStyleMap[state];
    if (!style) {
      return;
    }
    card.style.background = style.background;
    card.style.borderColor = style.border;
    card.style.color = style.text;
    const labelEl = card.querySelector(".label");
    if (labelEl) {
      labelEl.style.color = style.text;
    }
    const valueEl = card.querySelector(".value");
    if (valueEl) {
      valueEl.style.color = style.text;
    }
  };
  const applyCondenserCardStyle = (card, stateValue) => {
    if (!card) {
      return;
    }
    const text = (stateValue || "").trim().toLowerCase();
    const isOn = text.includes("on");
    const style = isOn ? coolingStyleMap.cooling : coolingStyleMap.idle;
    console.log("[condenser card] state:", stateValue, "isOn:", isOn, "style:", style);
    card.style.background = style.background;
    card.style.borderColor = style.border;
    card.style.color = style.text;
    const labelEl = card.querySelector(".label");
    if (labelEl) {
      labelEl.style.color = style.text;
    }
    const valueEl = card.querySelector(".value");
    if (valueEl) {
      valueEl.style.color = style.text;
    }
  };

  const gradientColorForCooling = (value) => {
    const ratio = Math.max(0, Math.min(value ?? 0, 1));
    const start = [211, 211, 211];
    const end = [0, 128, 64];
    const rgb = start.map((component, idx) =>
      Math.round(component + (end[idx] - component) * ratio)
    );
    return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
  };
  const buildSegmentGradient = (ctxSegment, startValue, endValue) => {
    const start = startValue ?? endValue ?? 50;
    const end = endValue ?? startValue ?? 50;
    if (!ctxSegment || !ctxSegment.chart || !ctxSegment.chart.ctx || !ctxSegment.p0 || !ctxSegment.p1) {
      return colorForPoint(end);
    }
    const gradient = ctxSegment.chart.ctx.createLinearGradient(
      ctxSegment.p0.x,
      ctxSegment.p0.y,
      ctxSegment.p1.x,
      ctxSegment.p1.y
    );
    gradient.addColorStop(0, colorForPoint(start));
    gradient.addColorStop(1, colorForPoint(end));
    return gradient;
  };
  const segmentColor = (ctxSegment) => {
    const startValue = ctxSegment.p0?.parsed.y ?? ctxSegment.parsed.y ?? 50;
    const endValue = ctxSegment.p1?.parsed.y ?? ctxSegment.parsed.y ?? startValue;
    return buildSegmentGradient(ctxSegment, startValue, endValue);
  };
  const buildCoolingGradient = (ctxSegment, startValue, endValue) => {
    const start = startValue ?? endValue ?? 0;
    const end = endValue ?? startValue ?? start;
    if (!ctxSegment || !ctxSegment.chart || !ctxSegment.chart.ctx || !ctxSegment.p0 || !ctxSegment.p1) {
      return gradientColorForCooling(end);
    }
    const gradient = ctxSegment.chart.ctx.createLinearGradient(
      ctxSegment.p0.x,
      ctxSegment.p0.y,
      ctxSegment.p1.x,
      ctxSegment.p1.y
    );
    gradient.addColorStop(0, gradientColorForCooling(start));
    gradient.addColorStop(1, gradientColorForCooling(end));
    return gradient;
  };
  const coolingSegmentColor = (ctxSegment) => {
    const startValue = ctxSegment.p0?.parsed.y ?? ctxSegment.parsed.y ?? 0;
    const endValue = ctxSegment.p1?.parsed.y ?? ctxSegment.parsed.y ?? startValue;
    return buildCoolingGradient(ctxSegment, startValue, endValue);
  };
  const fanColorMap = {
    auto: "#b4b4b4",
    circulate: "#a86c59",
    on: "#00ff7f",
  };
  const fanColorForValue = (value) => {
    const normalized = normalizeFanState(value);
    if (normalized === "C") {
      return fanColorMap.circulate;
    }
    if (normalized === "O") {
      return fanColorMap.on;
    }
    return fanColorMap.auto;
  };
  const buildFanGradient = (ctxSegment, startValue, endValue) => {
    if (!ctxSegment || !ctxSegment.chart || !ctxSegment.chart.ctx || !ctxSegment.p0 || !ctxSegment.p1) {
      return fanColorForValue(endValue);
    }
    const gradient = ctxSegment.chart.ctx.createLinearGradient(
      ctxSegment.p0.x,
      ctxSegment.p0.y,
      ctxSegment.p1.x,
      ctxSegment.p1.y
    );
    gradient.addColorStop(0, fanColorForValue(startValue));
    gradient.addColorStop(1, fanColorForValue(endValue));
    return gradient;
  };
  const fanSegmentColor = (ctxSegment) => {
    const startValue =
      ctxSegment.p0?.parsed?.y ??
      ctxSegment.p0?.parsed ??
      ctxSegment.parsed?.y ??
      ctxSegment.parsed ??
      0;
    const endValue =
      ctxSegment.p1?.parsed?.y ??
      ctxSegment.p1?.parsed ??
      ctxSegment.parsed?.y ??
      ctxSegment.parsed ??
      startValue;
    if (fanColorForValue(startValue) === fanColorForValue(endValue)) {
      return fanColorForValue(endValue);
    }
    return buildFanGradient(ctxSegment, startValue, endValue);
  };
  const fanSegmentDash = (ctxSegment) => {
    const value =
      ctxSegment.p1?.parsed?.y ??
      ctxSegment.p1?.parsed ??
      ctxSegment.p0?.parsed?.y ??
      ctxSegment.p0?.parsed ??
      ctxSegment.parsed?.y ??
      ctxSegment.parsed ??
      0;
    const numeric = fanStateToNumeric[normalizeFanState(value)] ?? 0;
    return numeric >= 2 ? [] : [4, 4];
  };

  const outsideWeatherIconPlugin = {
    id: "outsideWeatherIcon",
    afterDatasetsDraw: (chartInstance) => {
      const datasetIndex = 2;
      const meta = chartInstance.getDatasetMeta(datasetIndex);
      if (!meta || meta.hidden) {
        return;
      }
      if (!meta.data.length) {
        return;
      }
      const ctxChart = chartInstance.ctx;
      const flags = getOutsideFlags();
      const flagDays = getOutsideFlagDayChars();
      meta.data.forEach((point, idx) => {
        const flag = flags[idx];
        if (!flag || flagDays.length <= idx) {
          return;
        }
        const dayChar = flagDays[idx];
        const key = getWeatherGraphicKey(flag, dayChar);
        const img = weatherGraphicImages[key];
        if (!img || !img.complete) {
          return;
        }
        const chartHeight = chartInstance.height || 1;
        const size = Math.min(32, Math.max(24, Math.round((chartHeight / 420) * 30)));
        ctxChart.save();
        ctxChart.globalAlpha = 0.9;
        ctxChart.translate(point.x, point.y);
        ctxChart.beginPath();
        ctxChart.arc(0, 0, size / 2, 0, Math.PI * 2);
        ctxChart.clip();
        const gradient = ctxChart.createRadialGradient(0, 0, size * 0.05, 0, 0, size / 2);
        gradient.addColorStop(0, "rgba(255,255,255,0.9)");
        gradient.addColorStop(1, "rgba(255,255,255,0.0)");
        ctxChart.fillStyle = gradient;
        ctxChart.fillRect(-size / 2, -size / 2, size, size);
        ctxChart.globalAlpha = 1;
        ctxChart.drawImage(img, -size / 2, -size / 2, size, size);
        ctxChart.restore();
      });
    },
  };

  const destroyChart = () => {
    if (!chart) {
      return;
    }
    try {
      chart.destroy();
    } catch (err) {
      console.warn("Unable to destroy existing chart", err);
    } finally {
      chart = null;
    }
  };
  const updateLegendImage = () => {
    if (!chart || !chart.legend) {
      return;
    }
    const legendBox = chart.legend;
    let { left, top, width, height } = legendBox;
    if (!width || !height) {
      return;
    }
    try {
      height -= 275;
      width -= 20;
    } catch (error) {
      console.warn("Legend box adjustment error:", error);
    }
    if (!width || !height) {
      return;
    }
    const legendCanvas = document.createElement("canvas");
    legendCanvas.width = width;
    legendCanvas.height = height;
    const legendCtx = legendCanvas.getContext("2d");
    if (!legendCtx) {
      return;
    }
    legendCtx.drawImage(
      chart.canvas,
      left,
      top,
      width,
      height,
      0,
      0,
      width,
      height
    );
    const dataUrl = legendCanvas.toDataURL("image/png");
    const legendImg = document.getElementById("legend-image");
    if (legendImg && dataUrl) {
      legendImg.src = dataUrl;
    }
  };

  const createChart = () => {
    if (chart || !ctx) {
      return;
    }
    canvas.style.display = "block";
    const dataset = {
      labels: getChartLabels(),
      datasets: [
        {
          label: getSetpointLabel(),
          data: getSetpointSeries(),
          segment: {
            borderColor: segmentColor,
          },
          backgroundColor: "rgba(102,255,153,0.2)",
          spanGaps: true,
        },
        {
          label: getActualLabel(),
          data: getActualSeries(),
          segment: {
            borderColor: segmentColor,
          },
          backgroundColor: "rgba(125,164,255,0.2)",
          spanGaps: true,
        },
        {
          label: getOutsideLabel(),
          data: getOutsideSeries(),
          showLine: false,
          borderColor: "rgba(0,0,0,0)",
          pointRadius: 0,
          spanGaps: true,
        },
        {
          label: getCoolingLabel(),
          data: getCoolingSeries(),
          segment: {
            borderColor: coolingSegmentColor,
          },
          backgroundColor: "rgba(255,107,107,0.2)",
          yAxisID: "cooling",
          spanGaps: true,
          pointRadius: 0,
        },
        {
          label: "Fan Mode",
          data: getFanSeriesNumeric(),
          segment: {
            borderColor: fanSegmentColor,
          },
          backgroundColor: "rgba(255,165,0,0.3)",
          yAxisID: "fan",
          spanGaps: true,
          pointRadius: 0,
        },
      ],
    };
    chart = new Chart(ctx, {
      type: "line",
      data: dataset,
      plugins: [outsideWeatherIconPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: {
          padding: {
            right: 0,
          },
        },
        animation: false,
        scales: {
          y: {
            beginAtZero: false,
            min: 45,
            max: 100,
            ticks: {
              color: (ctxValue) => colorForPoint(ctxValue.tick.value),
            },
            grid: {
              color: "rgba(255,255,255,0.1)",
            },
          },
          fan: {
            type: "linear",
            position: "right",
            min: -1,
            max: 2,
            ticks: {
              stepSize: 1,
              callback: (value) => getFanLegend()[Math.round(value)] || "",
              color: (ctxValue) => {
                const tickValue = ctxValue.tick?.value ?? ctxValue.parsed ?? null;
                return fanColorForValue(tickValue);
              },
            },
            grid: {
              drawOnChartArea: false,
              color: "rgba(255,255,255,0.08)",
            },
          },
          cooling: {
            type: "linear",
            position: "right",
            offset: false,
            min: -1,
            max: 2,
            ticks: {
              stepSize: 1,
              callback: (value) => getCoolingLegend()[Math.round(value)] || "",
              color: (ctxValue) => {
                const numeric = Number(ctxValue.tick.value);
                return Number.isNaN(numeric) || numeric <= 0 ? "#ffd000" : "#32d15c";
              },
            },
            grid: {
              drawOnChartArea: true,
              color: "rgba(50,209,92,0.15)",
            },
          },
          x: {
            ticks: {
              color: "#f4f6ff",
              maxRotation: 0,
              minRotation: 90,
              padding: 8,
            },
            grid: {
              color: "rgba(255,255,255,0.08)",
            },
          },
        },
        interaction: {
          mode: "nearest",
          intersect: false,
          axis: "x",
          includeInvisible: true,
        },
        plugins: {
          legend: {
            position: "left",
            align: "start",
            labels: {
              color: "#f4f6ff",
              usePointStyle: false,
              boxWidth: 10,
            },
          },
          tooltip: {
            callbacks: {
              label: (context) => {
                const label = context.dataset.label || "";
              const seriesIndex = context.dataIndex;
              const minutes = getCondenserMinutes()[seriesIndex];
              const minuteLabel = formatMinutesValue(minutes);
            if (context.dataset.yAxisID === "fan") {
                const value = context.parsed?.y ?? context.parsed;
                return `${label}: ${fanLabelForValue(value) || "Unknown"}`;
              }
              if (context.dataset.yAxisID === "cooling") {
                const value = context.parsed.y;
                const statusLine = `${label}: ${getCoolingLegend()[Math.round(value)] || "Unknown"}`;
                if (minuteLabel) {
                  return [statusLine, "", `Runtime: ${minuteLabel}`];
                }
                return statusLine;
              }
                return `${label}: ${context.parsed.y ?? context.parsed}`;
            },
          },
          },
        },
      },
    });
    updateLegendImage();
  };

  const updateMetricCards = () => {
    const actualValue = getLatestActualValue();
    const setpointValue = getLatestSetpointValue();
    const outsideValue = getLatestOutsideValue();
    const outsideFlag = getOutsideFlag();
    const outsideDaylight = getOutsideDaylight();
    const outsideFlagColor = outsideFlagColors[outsideFlag] || null;
    const outsideCard = document.querySelector('.metric-card[data-metric="outside"]');
    const outsideText = formatOutsideDisplay(outsideValue);
    setCardValue(outsideCard, outsideText);
    applyCardColor(
      outsideCard,
      outsideFlagColor || gradientColorForOutside(outsideValue),
      outsideFlag === "N" ? "#fff" : null,
      outsideFlag === "S"
    );
    if (outsideCard) {
      let graphic = outsideCard.querySelector(".sunny-graphic");
      if (!graphic) {
        graphic = document.createElement("div");
        graphic.className = "sunny-graphic";
        outsideCard.appendChild(graphic);
      }
      let pathKey = outsideFlag;
      if (outsideFlag === "P") {
        pathKey = outsideDaylight ? "P-day" : "P-night";
      } else if (outsideFlag === "O") {
        pathKey = outsideDaylight ? "O-day" : "O-night";
      } else if (outsideFlag === "R") {
        pathKey = outsideDaylight ? "R-day" : "R-night";
      } else if (outsideFlag === "N") {
        pathKey = "N";
      }
      const path = weatherGraphicPaths[pathKey];
      if (path) {
        graphic.style.backgroundImage = `url("${path}")`;
        outsideCard.classList.add("sunny-image");
      } else {
        graphic.style.backgroundImage = "";
        outsideCard.classList.remove("sunny-image");
      }
    }
    const actualCard = document.querySelector('.metric-card[data-metric="actual"]');
    setCardValue(actualCard, formatTemperatureValue(actualValue));
    applyCardColor(actualCard, colorForPoint(actualValue));
    const setpointCard = document.querySelector('.metric-card[data-metric="setpoint"]');
    setCardValue(setpointCard, formatTemperatureValue(setpointValue));
    applyCardColor(setpointCard, colorForPoint(setpointValue));

    const fanCard = document.querySelector('.metric-card[data-metric="fan"]');
    const fanLabelRaw = getLatestFanRaw();
    const fanText = fanLabelRaw ? String(fanLabelRaw).trim() : fanStateLabels[normalizeFanState(fanLabelRaw)] || "Auto";
    setCardValue(fanCard, fanText);
    applyFanCardStyle(fanCard, getLatestFanValue());

    const coolingCard = document.querySelector('.metric-card[data-metric="cooling"]');
    setCardValue(coolingCard, getCoolingLegend()[Math.round(getLatestCoolingValue())] || "Idle");
    applyCoolingCardStyle(coolingCard, getLatestCoolingValue());
    const condenserCard = document.querySelector('.metric-card[data-metric="condenser-state"]');
    const condenserStateValue = getLatestCondenserState();
    if (condenserCard) {
      setCardValue(condenserCard, condenserStateValue || "Unknown");
      applyCondenserCardStyle(condenserCard, condenserStateValue);
    }
  };

  const datasetIndexByMode = {
    setpoint: 0,
    actual: 1,
    outside: 2,
    cooling: 3,
    fan: 4,
  };
  const enabledModes = new Set(Object.keys(datasetIndexByMode));
  const updateAxesVisibility = () => {
    if (!chart) {
      return;
    }
    const showTemp =
      enabledModes.has("setpoint") ||
      enabledModes.has("actual") ||
      enabledModes.has("outside");
    const showFan = enabledModes.has("fan");
    const showCooling = enabledModes.has("cooling");
    chart.options.scales.y.display = showTemp;
    chart.options.scales.y.ticks.display = showTemp;
    chart.options.scales.fan.display = showFan;
    chart.options.scales.cooling.display = showCooling;
    chart.options.scales.fan.ticks.display = showFan;
    chart.options.scales.cooling.ticks.display = showCooling;
  };
  const updateButtonStates = () => {
    if (!chartControlButtons) {
      return;
    }
    const allModesEnabled = Object.keys(datasetIndexByMode).every((mode) =>
      enabledModes.has(mode)
    );
    chartControlButtons.forEach((btn) => {
      const mode = btn.dataset.mode;
      if (mode === "both") {
        btn.classList.toggle("active", allModesEnabled);
      } else {
        btn.classList.toggle("active", enabledModes.has(mode));
      }
    });
  };
  const updateChartVisibility = () => {
    if (!chart) {
      return;
    }
    Object.entries(datasetIndexByMode).forEach(([mode, idx]) => {
      const dataset = chart.data.datasets[idx];
      if (!dataset) {
        return;
      }
      const nextHidden = !enabledModes.has(mode);
      dataset.hidden = nextHidden;
      const meta = chart.getDatasetMeta(idx);
      if (meta) {
        meta.hidden = nextHidden;
      }
    });
  };
  const toggleMode = (mode) => {
    if (mode === "both") {
      const allEnabled = Object.keys(datasetIndexByMode).every((m) =>
        enabledModes.has(m)
      );
      if (allEnabled) {
        enabledModes.clear();
      } else {
        Object.keys(datasetIndexByMode).forEach((m) => enabledModes.add(m));
      }
    } else if (mode) {
      if (enabledModes.has(mode)) {
        enabledModes.delete(mode);
      } else {
        enabledModes.add(mode);
      }
    }
    if (!chart) {
      createChart();
    }
    updateChartVisibility();
    updateAxesVisibility();
    updateButtonStates();
    if (chart) {
      chart.update();
    }
  };

  const showChart = () => {
    if (!chart) {
      createChart();
    }
    updateChartVisibility();
    updateAxesVisibility();
    updateButtonStates();
    if (canvas) {
      canvas.style.display = "block";
    }
    if (toggleHistoryBtn) {
      toggleHistoryBtn.textContent = "Hide History Chart";
      toggleHistoryBtn.classList.add("history-visible");
    }
    if (handsLogoTop) {
      handsLogoTop.classList.remove("hidden");
    }
  };

  const hideChart = () => {
    if (canvas) {
      canvas.style.display = "none";
    }
    if (toggleHistoryBtn) {
      toggleHistoryBtn.textContent = "Show History Chart";
      toggleHistoryBtn.classList.remove("history-visible");
    }
    if (handsLogoTop) {
      handsLogoTop.classList.add("hidden");
    }
  };

  function loadDashboardData(slug) {
    if (!slug) {
      logMessage("Missing archive slug.", "warn");
      return;
    }
    const url = buildArchiveJsonUrl(slug);
    if (!url) {
      logMessage(`Unable to build URL for slug ${slug}`, "warn");
      return;
    }
    fetch(url, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Status ${response.status}`);
        }
        return response.json();
      })
      .then((data) => {
        applyDashboardData(data, slug);
      })
      .catch((error) => {
        logMessage(`Failed to load archive ${slug}: ${error}`, "error");
      });
  }

  const setActiveArchiveItem = (slug) => {
    if (!chartHistoryList) {
      return;
    }
    chartHistoryList.querySelectorAll("button").forEach((btn) => {
      btn.classList.toggle("active", slug && btn.dataset.slug === slug);
    });
  };

  const closeHistoryList = () => {
    if (chartHistoryList) {
      chartHistoryList.classList.add("hidden");
    }
    if (chartHistoryToggle && chartHistoryToggle.classList.contains("history-visible")) {
      chartHistoryToggle.classList.remove("history-visible");
    }
  };

  const toggleHistoryList = () => {
    if (!chartHistoryList) {
      return;
    }
    chartHistoryList.classList.toggle("hidden");
    if (chartHistoryToggle) {
      const visible = !chartHistoryList.classList.contains("hidden");
      chartHistoryToggle.classList.toggle("history-visible", visible);
    }
  };

  const updateHistoryStatus = (slug) => {
    if (!chartHistoryStatus) {
      return;
    }
    const label = slug ? archiveLabelMap.get(slug) : null;
    chartHistoryStatus.textContent = label
      ? `History: ${label}`
      : "History: current data";
  };

  const updateTimestampDisplay = (text) => {
    if (!timestampDisplay) {
      return;
    }
    timestampDisplay.textContent = text || "History";
  };

  function renderArchiveList() {
    if (!chartHistoryList) {
      return;
    }
    const archiveDates = getArchiveDates();
    chartHistoryList.innerHTML = "";
    archiveLabelMap.clear();
    archiveDates.forEach((entry) => {
      const label = entry.label || entry.slug || "Unknown";
      const slug = entry.slug || "";
      if (slug) {
        archiveLabelMap.set(slug, label);
      }
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.dataset.slug = slug;
      button.addEventListener("click", (event) => {
        event.preventDefault();
        if (slug) {
          updateHistoryStatus(slug);
          currentArchiveSlug = slug;
          loadDashboardData(slug);
        }
        closeHistoryList();
      });
      item.appendChild(button);
      chartHistoryList.appendChild(item);
    });
    setActiveArchiveItem(currentArchiveSlug);
  }

  function applyDashboardData(data, slugHint = null) {
    if (!data) {
      return;
    }
    dashboardData = data;
    currentArchiveSlug = slugHint || data.generatedDateSlug || currentArchiveSlug;
    const isArchiveLoad = Boolean(slugHint);
    renderArchiveList();
    updateHistoryStatus(currentArchiveSlug);
    const timestampText =
      dashboardData.generatedTimestamp ||
      (currentArchiveSlug ? archiveLabelMap.get(currentArchiveSlug) : null) ||
      "History: current data";
    updateTimestampDisplay(timestampText);
    destroyChart();
    createChart();
    if (!isArchiveLoad || !cardsInitialized) {
      updateMetricCards();
      cardsInitialized = true;
    }
    if (chart) {
      chart.options.plugins.legend.display = false;
      chart.update();
    }
    showChart();
  }

  function getArchiveDates() {
    return getDashboardValue("archiveDates", []);
  }

    if (chartControlButtons) {
      chartControlButtons.forEach((button) => {
        button.addEventListener("click", () => {
          toggleMode(button.dataset.mode);
        });
      });
    }

  if (toggleHistoryBtn) {
    toggleHistoryBtn.addEventListener("click", () => {
      if (!canvas || canvas.style.display === "none") {
        showChart();
      } else {
        hideChart();
      }
    });
  }

  if (chartHistoryToggle && chartHistoryList) {
    chartHistoryToggle.addEventListener("click", () => {
      toggleHistoryList();
    });
  }

  applyDashboardData(dashboardData);
})();
