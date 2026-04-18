/**
 * 量化因子股票建议系统 - 前端逻辑
 */

// ============================================================
// 全局状态
// ============================================================
let currentCode = "";
let currentName = "";
let currentStrategy = "short";
let currentRange = "3m";
let allData = null;      // 完整分析数据
let klineChart = null;   // ECharts 实例

// ============================================================
// 搜索功能
// ============================================================

const searchInput = document.getElementById("searchInput");
const suggestions = document.getElementById("suggestions");
let debounceTimer = null;

searchInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => fetchSuggestions(searchInput.value, suggestions), 300);
});

searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doSearch();
});

function onTopSearchInput() {
    const input = document.getElementById("topSearchInput");
    const sugg = document.getElementById("topSuggestions");
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => fetchSuggestions(input.value, sugg), 300);
}

async function fetchSuggestions(q, container) {
    if (!q || q.length < 1) {
        container.classList.add("hidden");
        return;
    }
    try {
        const resp = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
        const data = await resp.json();
        if (!data.length) {
            container.classList.add("hidden");
            return;
        }
        container.innerHTML = data.map(s =>
            `<div class="suggestion-item" onclick="selectStock('${s.code}','${s.name}')">
                <span class="suggestion-code">${s.code}</span>
                <span class="suggestion-name">${s.name}</span>
            </div>`
        ).join("");
        container.classList.remove("hidden");
    } catch (e) {
        container.classList.add("hidden");
    }
}

function selectStock(code, name) {
    document.getElementById("suggestions").classList.add("hidden");
    document.getElementById("topSuggestions").classList.add("hidden");
    searchInput.value = code;
    document.getElementById("topSearchInput").value = "";
    loadStock(code);
}

function quickSearch(code) {
    searchInput.value = code;
    doSearch();
}

async function resolveAndLoad(rawInput) {
    const q = rawInput.trim();
    if (!q) return;

    // 如果已经是纯数字代码，直接加载
    const maybeCode = q.padStart(6, "0");
    if (/^\d{6}$/.test(maybeCode)) {
        loadStock(maybeCode);
        return;
    }

    // 名称/拼音搜索：先立即切换到分析页显示加载，后台解析代码
    document.getElementById("landing").classList.add("hidden");
    document.getElementById("mainPage").classList.remove("hidden");
    document.getElementById("stockInfo").innerHTML =
        `<span class="name">搜索中...</span><span class="code-label">${q}</span>`;
    document.getElementById("chartTitle").innerHTML =
        `<span class="chart-title-name">搜索 "${q}" 中...</span>`;

    if (!klineChart) {
        klineChart = echarts.init(document.getElementById("klineChart"), "dark");
        window.addEventListener("resize", () => klineChart && klineChart.resize());
    }
    klineChart.clear();
    klineChart.showLoading({ text: "正在搜索...", color: "#3b82f6", textColor: "#8899aa" });

    document.getElementById("recText").textContent = "搜索中...";
    document.getElementById("recText").className = "rec-text hold";
    document.getElementById("signalsList").innerHTML = `<div class="loading-text">正在搜索 "${q}"...</div>`;
    document.getElementById("newsList").innerHTML = `<div class="loading-text">等待搜索结果...</div>`;

    try {
        const resp = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
        const results = await resp.json();
        if (results.length === 0) {
            klineChart.hideLoading();
            document.getElementById("signalsList").innerHTML = `<div class="loading-text">未找到匹配的股票</div>`;
            document.getElementById("newsList").innerHTML = `<div class="loading-text">未找到</div>`;
            return;
        }
        // 找到股票，加载分析
        const stock = results[0];
        loadStock(stock.code);
    } catch (e) {
        klineChart.hideLoading();
        document.getElementById("signalsList").innerHTML = `<div class="loading-text">搜索失败: ${e.message}</div>`;
    }
}

function doSearch() {
    resolveAndLoad(searchInput.value);
}

function doTopSearch() {
    const input = document.getElementById("topSearchInput");
    document.getElementById("topSuggestions").classList.add("hidden");
    resolveAndLoad(input.value);
    input.value = "";
}

// ============================================================
// 加载股票数据
// ============================================================

async function loadStock(code) {
    // 确保是6位数字
    code = code.padStart(6, "0");
    if (!/^\d{6}$/.test(code)) {
        alert("请输入正确的6位股票代码");
        return;
    }

    currentCode = code;
    allData = null;

    // 立即切换到分析页面，显示加载骨架
    document.getElementById("landing").classList.add("hidden");
    document.getElementById("mainPage").classList.remove("hidden");

    // 更新顶部信息（先用代码占位）
    document.getElementById("stockInfo").innerHTML =
        `<span class="name">${code}</span><span class="code-label">加载中...</span>`;
    document.getElementById("chartTitle").innerHTML =
        `<span class="chart-title-name">${code}</span><span class="chart-title-code">加载中...</span>`;

    // 图表区域显示加载状态
    if (klineChart) {
        klineChart.clear();
        klineChart.showLoading({ text: "正在获取K线数据...", color: "#3b82f6", textColor: "#8899aa" });
    } else {
        const chartDom = document.getElementById("klineChart");
        klineChart = echarts.init(chartDom, "dark");
        window.addEventListener("resize", () => klineChart && klineChart.resize());
        klineChart.showLoading({ text: "正在获取K线数据...", color: "#3b82f6", textColor: "#8899aa" });
    }

    // 右侧面板显示加载状态
    document.getElementById("recText").textContent = "分析中...";
    document.getElementById("recText").className = "rec-text hold";
    document.getElementById("recStrength").textContent = "--";
    document.getElementById("recScore").textContent = "--";
    document.getElementById("levelCurrent").textContent = "--";
    document.getElementById("levelSupport").textContent = "--";
    document.getElementById("levelResistance").textContent = "--";
    document.getElementById("levelStopLoss").textContent = "--";
    document.getElementById("levelTarget").textContent = "--";
    document.getElementById("signalsList").innerHTML = `<div class="loading-text">正在计算技术指标...</div>`;
    document.getElementById("newsList").innerHTML = `<div class="loading-text">正在分析消息面...</div>`;

    try {
        // 加载图表 + 技术分析
        const resp = await fetch(`/api/stock/${code}`);
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || "请求失败");
        }
        allData = await resp.json();
        currentName = allData.name;

        // 更新顶部信息
        document.getElementById("stockInfo").innerHTML =
            `<span class="name">${currentName}</span><span class="code-label">${currentCode}</span>`;
        document.getElementById("chartTitle").innerHTML =
            `<span class="chart-title-name">${currentName}</span><span class="chart-title-code">${currentCode}</span>`;

        // 渲染图表 + 技术面
        klineChart.hideLoading();
        renderChart();
        updateRecommendation();

        // 保存到历史记录
        saveToHistory(code, currentName, allData);

    } catch (e) {
        if (klineChart) klineChart.hideLoading();
        document.getElementById("signalsList").innerHTML = `<div class="loading-text">加载失败: ${e.message}</div>`;
        document.getElementById("newsList").innerHTML = `<div class="loading-text">加载失败</div>`;
        return;
    }

    // 异步加载消息面（不阻塞）
    loadNewsSentiment(code);
}

async function loadNewsSentiment(code) {
    const newsList = document.getElementById("newsList");
    newsList.innerHTML = `<div class="loading-text">正在分析消息面...</div>`;

    try {
        const resp = await fetch(`/api/stock/${code}/news`);
        const data = await resp.json();
        if (data.error && !data.points) {
            newsList.innerHTML = `<div class="loading-text">${data.error}</div>`;
            return;
        }
        // 存储到 allData 供策略切换时使用
        allData.news_sentiment = data;
        // 更新历史记录中的消息面
        updateHistoryNews(code, data);
        // 重新渲染消息面
        updateNewsPanel(data);
    } catch (e) {
        newsList.innerHTML = `<div class="loading-text">消息面数据暂时不可用</div>`;
    }
}

function updateNewsPanel(sentiment) {
    const newsList = document.getElementById("newsList");
    if (sentiment.points && sentiment.points.length > 0) {
        newsList.innerHTML = sentiment.points.map(p => {
            const icon = p.bias === "positive" ? "+" : p.bias === "negative" ? "-" : "=";
            const action = p.bias === "positive" ? "buy" : p.bias === "negative" ? "sell" : "hold";
            return `<div class="signal-item ${action}">
                <span class="signal-icon">${icon}</span>
                <div class="signal-content">
                    <span class="signal-name">${p.text}</span>
                </div>
            </div>`;
        }).join("");
    } else {
        newsList.innerHTML = `<div class="loading-text">暂无消息面数据</div>`;
    }
}

// ============================================================
// ECharts K线图
// ============================================================

function initChart() {
    const dom = document.getElementById("klineChart");
    if (!klineChart) {
        klineChart = echarts.init(dom, "dark");
        window.addEventListener("resize", () => klineChart && klineChart.resize());
    }
    klineChart.hideLoading();
    renderChart();
}

function getFilteredData() {
    if (!allData || !allData.chart_data) return [];
    const data = allData.chart_data;
    const total = data.length;
    // 全部标签直接返回所有数据，其余按时间窗口截取
    if (currentRange === "all") return data;
    let count;
    switch (currentRange) {
        case "3m": count = Math.min(60, total); break;
        case "6m": count = Math.min(120, total); break;
        case "1y": count = Math.min(250, total); break;
        default: count = total;
    }
    return data.slice(-count);
}

function renderChart() {
    const raw = getFilteredData();
    if (!raw.length) return;

    // 拆分数据
    const dates = raw.map(d => d.date);
    const ohlc = raw.map(d => [d.open, d.close, d.low, d.high]);
    const volumes = raw.map(d => d.volume);
    const ma5 = raw.map(d => d.MA5);
    const ma10 = raw.map(d => d.MA10);
    const ma20 = raw.map(d => d.MA20);
    const ma60 = raw.map(d => d.MA60);
    const dif = raw.map(d => d.DIF);
    const dea = raw.map(d => d.DEA);
    const macdBar = raw.map(d => d.MACD_bar);

    const volColors = raw.map(d => d.close >= d.open ? "#22c55e" : "#ef4444");

    klineChart.setOption({
        animation: false,
        backgroundColor: "transparent",
        tooltip: {
            trigger: "axis",
            axisPointer: { type: "cross" },
            backgroundColor: "rgba(17,24,39,0.95)",
            borderColor: "#2a3a50",
            textStyle: { color: "#e8edf5", fontSize: 12 }
        },
        axisPointer: {
            link: [{ xAxisIndex: "all" }]
        },
        grid: [
            { left: "8%", right: "3%", top: "3%", height: "46%" },   // K线
            { left: "8%", right: "3%", top: "53%", height: "10%" },  // 成交量
            { left: "8%", right: "3%", top: "67%", height: "12%" },  // MACD
        ],
        xAxis: [
            { type: "category", data: dates, gridIndex: 0, axisLine: { lineStyle: { color: "#2a3a50" } }, axisLabel: { show: false } },
            { type: "category", data: dates, gridIndex: 1, axisLine: { lineStyle: { color: "#2a3a50" } }, axisLabel: { show: false } },
            { type: "category", data: dates, gridIndex: 2, axisLine: { lineStyle: { color: "#2a3a50" } }, axisLabel: { color: "#8899aa", fontSize: 10 } },
        ],
        yAxis: [
            { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: "#1a2332" } }, axisLabel: { color: "#8899aa" } },
            { scale: true, gridIndex: 1, splitLine: { show: false }, axisLabel: { show: false } },
            { scale: true, gridIndex: 2, splitLine: { lineStyle: { color: "#1a2332" } }, axisLabel: { color: "#8899aa", fontSize: 10 } },
        ],
        dataZoom: [
            { type: "inside", xAxisIndex: [0, 1, 2], start: 0, end: 100 },
            {
                type: "slider",
                xAxisIndex: [0, 1, 2],
                bottom: 0,
                height: 24,
                borderColor: "#2a3a50",
                backgroundColor: "#111827",
                fillerColor: "rgba(59,130,246,0.15)",
                handleStyle: { color: "#3b82f6", borderColor: "#3b82f6" },
                textStyle: { color: "#8899aa", fontSize: 10 },
                dataBackground: {
                    lineStyle: { color: "#2a3a50" },
                    areaStyle: { color: "rgba(59,130,246,0.1)" }
                },
                selectedDataBackground: {
                    lineStyle: { color: "#3b82f6" },
                    areaStyle: { color: "rgba(59,130,246,0.2)" }
                }
            }
        ],
        series: [
            // K线
            {
                name: "K线",
                type: "candlestick",
                data: ohlc,
                xAxisIndex: 0,
                yAxisIndex: 0,
                itemStyle: {
                    color: "#22c55e",       // 阳线填充
                    color0: "#ef4444",      // 阴线填充
                    borderColor: "#22c55e",
                    borderColor0: "#ef4444"
                }
            },
            // MA5
            {
                name: "MA5",
                type: "line",
                data: ma5,
                xAxisIndex: 0,
                yAxisIndex: 0,
                smooth: true,
                symbol: "none",
                lineStyle: { width: 1.2, color: "#f59e0b" }
            },
            // MA10
            {
                name: "MA10",
                type: "line",
                data: ma10,
                xAxisIndex: 0,
                yAxisIndex: 0,
                smooth: true,
                symbol: "none",
                lineStyle: { width: 1.2, color: "#3b82f6" }
            },
            // MA20
            {
                name: "MA20",
                type: "line",
                data: ma20,
                xAxisIndex: 0,
                yAxisIndex: 0,
                smooth: true,
                symbol: "none",
                lineStyle: { width: 1.2, color: "#a855f7" }
            },
            // MA60
            {
                name: "MA60",
                type: "line",
                data: ma60,
                xAxisIndex: 0,
                yAxisIndex: 0,
                smooth: true,
                symbol: "none",
                lineStyle: { width: 1.2, color: "#64748b" }
            },
            // 成交量
            {
                name: "成交量",
                type: "bar",
                data: volumes.map((v, i) => ({
                    value: v,
                    itemStyle: { color: volColors[i] + "88" }
                })),
                xAxisIndex: 1,
                yAxisIndex: 1
            },
            // DIF
            {
                name: "DIF",
                type: "line",
                data: dif,
                xAxisIndex: 2,
                yAxisIndex: 2,
                symbol: "none",
                lineStyle: { width: 1.2, color: "#f59e0b" }
            },
            // DEA
            {
                name: "DEA",
                type: "line",
                data: dea,
                xAxisIndex: 2,
                yAxisIndex: 2,
                symbol: "none",
                lineStyle: { width: 1.2, color: "#3b82f6" }
            },
            // MACD柱
            {
                name: "MACD",
                type: "bar",
                data: macdBar.map(v => ({
                    value: v,
                    itemStyle: { color: v >= 0 ? "#22c55e88" : "#ef444488" }
                })),
                xAxisIndex: 2,
                yAxisIndex: 2
            }
        ]
    }, true);
}

function switchRange(btn) {
    document.querySelectorAll(".chart-tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentRange = btn.dataset.range;
    if (allData) renderChart();
}

// ============================================================
// 推荐面板
// ============================================================

function switchStrategy(btn) {
    document.querySelectorAll(".strategy-tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentStrategy = btn.dataset.strategy;
    updateRecommendation();
}

function updateRecommendation() {
    if (!allData) return;

    const rec = allData.recommendations[currentStrategy];

    // 核心建议
    const recText = document.getElementById("recText");
    const action = getAction(rec.recommendation);
    recText.textContent = rec.recommendation;
    recText.className = "rec-text " + action;

    document.getElementById("recStrength").textContent = rec.strength;
    document.getElementById("recScore").textContent = rec.score.toFixed(2);

    // 关键价位
    const lv = rec.key_levels;
    document.getElementById("levelCurrent").textContent = lv.current;
    document.getElementById("levelSupport").textContent = lv.support;
    document.getElementById("levelResistance").textContent = lv.resistance;
    document.getElementById("levelStopLoss").textContent = lv.stop_loss;
    document.getElementById("levelTarget").textContent = lv.target;

    // 技术面信号
    const signalsList = document.getElementById("signalsList");
    if (rec.signals && rec.signals.length > 0) {
        signalsList.innerHTML = rec.signals.map(s => {
            const icon = s.action === "buy" ? "+" : s.action === "sell" ? "-" : "=";
            return `<div class="signal-item ${s.action}">
                <span class="signal-icon">${icon}</span>
                <div class="signal-content">
                    <span class="signal-name">${s.name}</span>
                    <span class="signal-desc">${s.desc}</span>
                </div>
            </div>`;
        }).join("");
    } else {
        signalsList.innerHTML = `<div class="loading-text">暂无明确信号</div>`;
    }

    // 消息面（如果已加载则渲染，否则保持"正在分析"状态）
    if (allData.news_sentiment) {
        updateNewsPanel(allData.news_sentiment);
    }
}

function getAction(rec) {
    if (rec.includes("买入")) return "buy";
    if (rec.includes("卖出")) return "sell";
    return "hold";
}

// ============================================================
// 历史记录（localStorage）
// ============================================================

const HISTORY_KEY = "stock_history";
const HISTORY_MAX = 15;

function loadHistory() {
    try {
        return JSON.parse(localStorage.getItem(HISTORY_KEY)) || [];
    } catch (e) {
        return [];
    }
}

function saveHistory(list) {
    try {
        localStorage.setItem(HISTORY_KEY, JSON.stringify(list));
    } catch (e) {
        // localStorage 满了，删掉最旧的一半
        localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, Math.ceil(HISTORY_MAX / 2))));
    }
}

function saveToHistory(code, name, data) {
    const list = loadHistory();
    // 去重：移除同代码的旧记录
    const filtered = list.filter(h => h.code !== code);
    filtered.unshift({
        code,
        name,
        timestamp: Date.now(),
        data
    });
    // 限制数量
    saveHistory(filtered.slice(0, HISTORY_MAX));
}

function updateHistoryNews(code, newsData) {
    const list = loadHistory();
    const item = list.find(h => h.code === code);
    if (item && item.data) {
        item.data.news_sentiment = newsData;
        saveHistory(list);
    }
}

function formatTime(ts) {
    const d = new Date(ts);
    const now = new Date();
    const pad = n => String(n).padStart(2, "0");
    const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    // 今天的只显示时间，非今天显示日期
    if (d.toDateString() === now.toDateString()) return time;
    return `${d.getMonth() + 1}/${d.getDate()} ${time}`;
}

function renderHistory() {
    const section = document.getElementById("historySection");
    const container = document.getElementById("historyList");
    const list = loadHistory();
    if (!list.length) {
        section.classList.add("hidden");
        return;
    }
    section.classList.remove("hidden");
    container.innerHTML = list.map(h => `
        <div class="history-item" onclick="loadFromHistory('${h.code}')">
            <span class="h-name">${h.name}</span>
            <span class="h-code">${h.code}</span>
            <span class="h-time">${formatTime(h.timestamp)}</span>
            <span class="h-refresh" onclick="event.stopPropagation(); loadStock('${h.code}')" title="重新加载">&#x21bb;</span>
        </div>
    `).join("");
}

function loadFromHistory(code) {
    const list = loadHistory();
    const item = list.find(h => h.code === code);
    if (!item || !item.data) {
        loadStock(code);
        return;
    }

    currentCode = item.code;
    currentName = item.name;
    allData = item.data;

    // 立即切换到分析页面
    document.getElementById("landing").classList.add("hidden");
    document.getElementById("mainPage").classList.remove("hidden");

    // 更新顶部信息
    document.getElementById("stockInfo").innerHTML =
        `<span class="name">${currentName}</span><span class="code-label">${currentCode}</span>`;
    document.getElementById("chartTitle").innerHTML =
        `<span class="chart-title-name">${currentName}</span><span class="chart-title-code">${currentCode}</span>`;

    // 渲染图表和推荐
    if (klineChart) {
        klineChart.clear();
    } else {
        const chartDom = document.getElementById("klineChart");
        klineChart = echarts.init(chartDom, "dark");
        window.addEventListener("resize", () => klineChart && klineChart.resize());
    }
    klineChart.hideLoading();
    renderChart();
    updateRecommendation();

    // 如果没有消息面数据，异步加载
    if (!allData.news_sentiment) {
        loadNewsSentiment(code);
    }
}

function refreshStock() {
    if (currentCode) {
        loadStock(currentCode);
    }
}

// ============================================================
// UI 辅助
// ============================================================

function showLoading(show) {
    document.getElementById("loadingOverlay").classList.toggle("hidden", !show);
}

function goHome() {
    document.getElementById("mainPage").classList.add("hidden");
    document.getElementById("landing").classList.remove("hidden");
    searchInput.value = "";
    searchInput.focus();
    renderHistory();
}

// 点击空白处关闭建议
document.addEventListener("click", (e) => {
    if (!e.target.closest(".search-box-outer")) {
        suggestions.classList.add("hidden");
    }
    if (!e.target.closest(".top-search")) {
        document.getElementById("topSuggestions").classList.add("hidden");
    }
});

// 搜索框聚焦
if (searchInput) searchInput.focus();
// 首页渲染历史记录
renderHistory();
