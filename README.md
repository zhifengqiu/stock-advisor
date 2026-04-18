# 量化因子 - 股票操作建议系统

基于技术面（MA/MACD/RSI/KDJ/布林带/成交量）+ 消息面（PE/PB估值/新闻情感分析）的多维度量化分析系统，提供短线/中线/长线操作建议。

**在线体验**: https://stock-advisor-edpv.onrender.com

## 功能特性

| 功能 | 说明 |
|------|------|
| 智能搜索 | 支持股票代码、中文名称、拼音首字母、全拼搜索（对齐同花顺） |
| K线图表 | ECharts 交互式K线，叠加 MA5/10/20/60 均线 + 成交量 + MACD |
| 拖拽缩放 | 底部滑动条支持拖拽平移和缩放，可浏览全部历史数据 |
| 三线策略 | 短线(1-5天)、中线(1-3月)、长线(3月+) 独立量化评分 |
| 技术面信号 | MA金叉死叉、KDJ超买超卖、RSI、MACD、布林带、量比分析 |
| 消息面分析 | PE/PB估值评估、个股新闻关键词情感分析 |
| 关键价位 | 自动计算支撑位、压力位、建议止损价、目标价 |
| 历史记录 | 分析结果自动保存，可一键查看历史或重新加载 |
| 多数据源 | 东财(akshare) → 新浪财经 → 本地JSON文件，三级兜底 |

## 项目结构

```
stock-advisor/
├── app.py                  # Flask 后端 + 量化分析引擎（核心文件）
├── requirements.txt        # Python 依赖
├── render.yaml             # Render.com 部署配置
├── stock_list_cache.json   # 5505只A股列表缓存
├── .gitignore
├── templates/
│   └── index.html          # 主页面（搜索框 + 图表 + 建议面板）
└── static/
    ├── css/
    │   └── style.css       # 暗色交易主题样式
    └── js/
        └── main.js         # 前端交互 + ECharts 图表渲染
```

## 本地开发

### 环境要求

- Python 3.9+
- pip

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/zhifengqiu/stock-advisor.git
cd stock-advisor

# 2. 创建虚拟环境（推荐）
python -m venv venv

# Windows 激活:
venv\Scripts\activate
# Linux/Mac 激活:
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动应用
python app.py
```

启动后浏览器访问 http://127.0.0.1:5000

## 部署到 Render.com（免费）

### 前提条件

- GitHub 账号
- 代码已推送到 GitHub 仓库

### 部署步骤

1. **登录 Render**: 打开 https://render.com ，点击 "Get Started" 使用 GitHub 账号登录

2. **创建 Web Service**:
   - 点击右上角 **New** → **Web Service**
   - 在仓库列表中找到 `stock-advisor` 并点击 **Connect**
   - 如果看不到仓库，点击页面底部的 **+ Connect account** 给 Render 授权访问你的 GitHub 仓库

3. **配置部署参数**（Render 会自动识别 `render.yaml`，确认即可）:

   | 配置项 | 值 |
   |--------|-----|
   | Name | `stock-advisor` |
   | Runtime | Python 3 |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120 --max-requests 50` |
   | Plan | Free |

4. **点击 "Create Web Service"** 开始部署

5. **等待构建完成**（首次约 3-5 分钟），部署成功后页面顶部会显示访问地址：
   ```
   https://stock-advisor-xxxx.onrender.com
   ```

### 注意事项

- 免费 tier 服务在 **15分钟无请求后自动休眠**，首次唤醒需约 30 秒
- Render 服务器位于海外，访问国内金融 API 可能较慢（通常 3-8 秒）
- 免费月度流量限额 750 小时运行时间，个人使用足够

---

## 架构设计

### API 拆分（渐进式加载）

系统将数据加载拆分为两个独立接口，确保页面快速响应：

| 接口 | 返回内容 | 响应速度 |
|------|----------|----------|
| `GET /api/stock/<code>` | K线数据 + 技术指标分析 | 快（纯计算） |
| `GET /api/stock/<code>/news` | PE/PB估值 + 新闻情感分析 | 慢（需调外部API） |

前端加载流程：
1. 点击搜索 → **立即跳转**分析页（不等API）
2. 主接口返回 → 渲染K线图 + 技术面建议
3. 消息面接口异步返回 → 渲染估值和新闻

### 搜索优化

搜索接口优先使用本地缓存（`stock_list_cache.json`，5505只A股），**15ms 响应**：
- 内存缓存 → 本地JSON文件 → API（仅兜底尝试一次）
- 搜索时不会阻塞在 API 重试上

### 内存优化（Render 512MB 限制）

| 优化项 | 说明 |
|--------|------|
| 单股查询 | 消息面用百度估值API查询单只股票PE/PB，不加载全市场5500只 |
| 及时释放 | `del df; gc.collect()` 主动回收 DataFrame 内存 |
| Worker配置 | 1 worker + 120s超时 + 50请求后回收 |
| 非关键降频 | 消息面API仅重试1次，失败快速跳过 |

---

## 常见问题与处理

### 1. 搜索无结果

**现象**: 输入股票名称或代码后提示"未找到匹配的股票"

**原因**: 股票列表数据源（东财API + 新浪API）均不可达，且无本地缓存文件

**处理方案**:
- 首次启动时会自动从东财/新浪拉取全A股列表（约5500只）
- 拉取成功后会保存到 `stock_list_cache.json` 本地文件
- 如果两个API都失败，程序会从本地文件加载
- 如果本地文件也不存在，则搜索功能不可用，需等网络恢复后重启

**手动重建缓存**:
```python
# 在项目目录运行
python -c "
from app import get_stock_list
stocks = get_stock_list(force_refresh=True)
print(f'缓存重建完成: {len(stocks)} 只')
"
```

### 2. 搜索联想太慢（几十秒才出结果）

**原因**: 搜索接口首次调用时，`get_stock_list()` 尝试从东财API拉取数据，网络不通时会重试3次（每次指数退避），总计可能等待 30+ 秒

**处理方案（已优化）**:
- 搜索接口已优化为**优先使用本地缓存**，不再等API重试
- 首次部署后需要触发一次数据加载（手动访问 `/api/stock/<任意代码>` 即可预热）
- 确保代码仓库中包含 `stock_list_cache.json` 文件

### 3. 分析失败（ConnectionError / RemoteDisconnected）

**现象**: 点击分析后提示 "分析失败: Connection aborted"

**原因**: 东方财富和新浪财经的API间歇性不稳定，网络波动时会出现

**处理方案**:
- 程序已内置三级兜底机制：
  1. 东财API（带重试 + 指数退避）
  2. 新浪财经API（备用数据源）
  3. 本地缓存文件
- 通常等几分钟后重试即可恢复
- 如果持续失败，检查网络是否能访问 `money.finance.sina.com.cn`

### 4. Render 部署 HTTP 500 + Worker OOM (SIGKILL)

**现象**: Render 日志显示 `CRITICAL ... SIGKILL! Perhaps out of memory?`

**原因**: 
1. 消息面分析调用 `stock_zh_a_spot_em()` 一次性加载全市场5500+只股票行情，内存爆表
2. Worker 配置不当（workers=2，无超时限制）
3. Python 版本过新（3.14），部分库不兼容

**处理方案（已修复）**:
- 消息面改用百度估值API（`stock_zh_valuation_baidu`），仅查询单只股票
- API拆分为图表+消息面两个独立接口，消息面失败不影响主分析
- `render.yaml` 配置：`workers=1, timeout=120, max-requests=50`
- `PYTHON_VERSION` 固定为 `3.11.6`

### 5. K线图不显示

**现象**: 分析页面加载成功但K线图区域空白

**原因**: 
- 代码中使用 `innerHTML = ""` 清空 ECharts 容器，导致 ECharts 实例与DOM脱离
- 浏览器缓存旧版 JS 文件

**处理方案（已修复）**:
- 改用 `klineChart.clear()` 清除图表数据，保留ECharts实例
- 静态资源URL带时间戳参数 `?v=<timestamp>`，每次部署自动刷新缓存

### 6. 部署到 Render 后构建失败

**现象**: Render 部署日志显示 `pip install` 报错

**常见原因与处理**:

| 错误信息 | 原因 | 解决方案 |
|----------|------|----------|
| `numpy` 编译失败 | Python 版本不兼容 | 确认 `render.yaml` 中 `PYTHON_VERSION` 为 3.11 |
| `akshare` 安装失败 | 依赖冲突 | 检查 `requirements.txt` 版本约束 |
| `gunicorn` 找不到 | 未添加到依赖 | 确认 `requirements.txt` 包含 `gunicorn>=21.2` |
| `ModuleNotFoundError` | 缺少依赖包 | 执行 `pip install -r requirements.txt` 检查 |

### 7. Render 部署成功但页面打不开

**现象**: 点击链接后显示 502 或超时

**处理方案**:
- 检查 Render 日志中 `Start Command` 是否正常执行
- 确认 Start Command 是 `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120 --max-requests 50`
- 查看 Render 日志是否有 Python 报错

### 8. 图表不显示

**现象**: 页面加载了但K线图区域空白

**可能原因**:
- ECharts CDN 加载失败（网络问题）
- 股票数据为空（API 全部失败）

**处理方案**:
- 检查浏览器控制台（F12）是否有 JavaScript 报错
- 刷新页面重试
- 如果是部署环境，可能需要更换 ECharts CDN 源

### 9. 部署后更新代码

本地修改代码后，推送到 GitHub 即可自动触发 Render 重新部署：

```bash
git add .
git commit -m "描述你的修改"
git push
```

Render 会在 1-2 分钟内自动完成重新部署。

---

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python Flask |
| 数据源 | akshare (东财) + 新浪财经 + 百度估值 + 本地JSON缓存 |
| 技术指标 | 纯 Python 实现（无 TA-Lib 依赖） |
| 拼音搜索 | pypinyin |
| 前端图表 | ECharts 5 |
| 前端缓存 | localStorage（历史记录） |
| 服务器 | gunicorn |
| 部署 | Render.com |

## 量化因子体系

| 策略 | 关注指标 | 信号类型 |
|------|----------|----------|
| **短线** (1-5天) | MA5/MA10、KDJ、RSI6、成交量异动、价格偏离度 | 超买超卖、金叉死叉、放量/缩量 |
| **中线** (1-3月) | MA20/MA60、MACD、布林带%b、20日涨跌幅 | 趋势方向、动能转换 |
| **长线** (3月+) | MA60/MA120、MACD零轴、均线斜率、60日涨跌幅 | 大趋势判断、估值回归 |

## 免责声明

本项目仅供学习和研究使用，不构成任何投资建议。股市有风险，投资需谨慎。
