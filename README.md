# 顺为数据

一个零成本、无登录、无数据库的个人 A 股复盘 PWA。

每天盘后抓取两部分数据，统一写入 `data.json`：

1. **大盘盘面**：全市场个股涨跌幅分布、涨停/跌停家数、沪深北三市成交额；
2. **ETF 复盘**：4 只沪深300ETF的每日一级市场净申购与总市值。

前端用 Chart.js 直接读取 `data.json` 绘图，移动端自适应，可添加到手机桌面。

> 当前仓库里的 `data.json` 是**界面预览用演示数据**（`demo: true`），不是真实行情。首次运行 GitHub Actions 后会完整回补并替换，页面演示标记会自动消失。

---

## 功能

### 大盘盘面

- 当日 A 股全市场个股涨跌分布柱状图；
- 8 个区间：`>10%`、`7%~10%`、`3%~7%`、`0~3%`、`0~-3%`、`-3%~-7%`、`-7%~-10%`、`<-10%`；
- 上涨 / 平盘 / 下跌家数、交易个股数；
- 大盘盘面模块下方：涨停家数、跌停家数、沪深北三市成交额。

### ETF 复盘

| 代码 | 基金 | 交易所 |
|---|---|---|
| 510300 | 华泰柏瑞沪深300ETF | 上交所 |
| 510310 | 易方达沪深300ETF | 上交所 |
| 510330 | 华夏沪深300ETF | 上交所 |
| 159919 | 嘉实沪深300ETF | 深交所 |

- 近 180 个交易日每日份额、单位净值；
- 每日净申购折线图；
- 每日总市值折线图；
- 近 30 / 90 / 180 日切换；
- 份额拆分/合并自动识别，事件日净申购记 0。

### PWA

- 可添加到 iPhone / Android 桌面；
- Service Worker 缓存页面和最近一次 `data.json`；
- 图表库不可用时自动切换内置 Canvas 兼容渲染。

---

## 计算口径

### 大盘涨跌分布

- 数据源：AKShare `stock_zh_a_spot_em()`，东方财富沪深京 A 股行情；
- 取每只个股当日收盘涨跌幅，按 8 个区间计数；
- 涨停/跌停按板块涨跌停幅度与收盘涨跌幅统计：
  - 主板 10%，创业板/科创板 20%，北交所 30%，ST 5%；
  - 容差 ±0.35 个百分点；
  - 排除名称以 `N` / `C` 开头的新股；
- 成交额为全市场个股 `成交额` 求和，单位换算为亿元；
- 该口径是**收盘涨跌幅统计**，不是交易所官方涨停封板池；如需逐只封单、连板数据，可再接入 `stock_zt_pool_em`。

### ETF 净申购与总市值

```text
净申购(亿元) = (当日份额 - 前一交易日份额) × 当日单位净值
总市值(亿元) = 当日份额 × 当日单位净值
```

- 份额统一为**亿份**，单位净值单位为**元**，金额单位为**亿元**；
- 净申购是一级市场申赎估算，**不等同场内资金净流入**；
- 总市值是基金资产规模，不是按收盘价计算的场内市值。

### 拆分/合并

若某日份额相对前一日跳变超过约 35%，且 `份额变化倍数 × 净值变化倍数` 接近 1，则识别为拆分/合并：

- 该日净申购记为 `0`；
- 总市值仍用原始份额 × 净值；
- `events` 记录事件。

---

## 数据源

全部免费、公开：

| 数据 | 来源 | AKShare 函数 |
|---|---|---|
| 全市场个股涨跌幅、成交额 | 东方财富沪深京 A 股 | `stock_zh_a_spot_em()` |
| 上交所每日 ETF 份额 | 上交所 ETF 基金规模 | `fund_etf_scale_sse(date=...)` |
| 深交所每日 ETF 份额 | 深交所基金规模日频 | `fund_scale_daily_szse(start_date, end_date, symbol="ETF")` |
| 场内基金历史单位净值 | 东方财富天天基金 | `fund_etf_fund_info_em(fund, start_date, end_date)` |
| 交易日历 | 新浪财经 | `tool_trade_date_hist_sina()` |

官方页面：

- 上交所 ETF 基金规模：<https://www.sse.com.cn/assortment/fund/etf/list/scale/>
- 深交所基金规模日频：<https://www.szse.cn/market/fund/volume/etf/index.html>
- 东方财富历史净值示例：<https://fundf10.eastmoney.com/jjjz_510300.html>

> 东方财富、腾讯、新浪的实时行情接口只能提供价格、成交额、IOPV 等，**没有 180 天每日 ETF 份额历史**。核心份额必须用交易所公开数据；交易所接口本身免费。

---

## 项目结构

```text
.
├── index.html                  # 页面
├── styles.css                  # 极简样式 / 深色模式
├── app.js                      # 读取 data.json、Chart.js 绘图、PWA 安装
├── manifest.webmanifest        # PWA 清单
├── sw.js                       # Service Worker
├── data.json                   # 抓取结果（当前为演示数据）
├── icons/                      # PWA 图标
├── scripts/
│   └── fetch_data.py           # AKShare 抓取与计算
├── tests/
│   └── test_calc.py            # 计算与主流程测试
├── tools/
│   ├── make_icons.py           # 重新生成图标
│   └── make_demo_data.py       # 重新生成演示 data.json
├── .github/workflows/
│   └── update-data.yml         # 定时抓取 + 提交 data.json
├── requirements.txt
└── README.md
```

---

## 本地运行

需要 Python 3.12 左右版本。

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

# 首次完整回补近 180 个交易日 + 当日大盘盘面
python scripts/fetch_data.py --full --output data.json

# 之后日常增量更新
python scripts/fetch_data.py --output data.json
```

启动静态页面：

```bash
python -m http.server 8000
```

打开 `http://127.0.0.1:8000/`。Service Worker 只在 `localhost` 或 HTTPS 下生效。

运行测试：

```bash
python -m unittest discover -s tests -v
```

### 命令行参数

```text
--output PATH       输出文件，默认仓库根目录 data.json
--days N            输出交易日数量，默认 180
--full              忽略已有 data.json，完整回补
--end-date YYYY-MM-DD  指定截止日期（调试用）
```

---

## 部署：GitHub Pages + GitHub Actions

按沟通结果，定时抓取放在 GitHub Actions，完全免费。脚本本身也能在 Replit 运行，但 Replit 免费版没有可靠的每天 18:00 定时任务。

### 1. 创建仓库

在 GitHub 新建仓库，建议 **Public**（GitHub Pages 公共仓库免费；Actions 额度足够）。

### 2. 上传文件

```bash
git init
git add .
git commit -m "feat: shunwei data dashboard"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

### 3. 开启 GitHub Pages

仓库 **Settings → Pages**：

- Source：`Deploy from a branch`
- Branch：`main`
- Folder：`/ (root)`

页面地址：

```text
https://<你的用户名>.github.io/<仓库名>/
```

如果仓库名是 `<用户名>.github.io`，地址是 `https://<用户名>.github.io/`。页面使用相对路径，两种地址都支持。

### 4. 开启 Actions 写权限

**Settings → Actions → General → Workflow permissions**：

- 选择 **Read and write permissions**；
- 保存。

否则 Actions 能抓取数据，但无法把 `data.json` 提交回仓库。

### 5. 首次完整回补

进入 **Actions → Update market data → Run workflow**：

- 勾选 `full_backfill`；
- 点击运行。

首次会逐个交易日抓取上交所份额，约需几分钟。完成后 `data.json` 变为真实数据，演示标记消失。

之后每个交易日北京时间 **18:10、19:10、20:30** 自动运行。GitHub 的 cron 可能有几分钟延迟，属于正常现象。

---

## 定时任务

```yaml
schedule:
  - cron: "10 10 * * 1-5"   # 北京时间 18:10
  - cron: "10 11 * * 1-5"   # 北京时间 19:10
  - cron: "30 12 * * 1-5"   # 北京时间 20:30
```

- GitHub Actions cron 使用 **UTC**，上面已经换算；
- 18:10 首跑，净值/份额/全市场行情不齐时，19:10、20:30 自动补跑；
- 数据没有变化时不会产生无意义 commit；
- 最新交易日数据不齐时，`data_date` 保留最近完整交易日，页面标记“待补跑”。

---

## PWA 添加到桌面

### iPhone / iPad

1. 用 **Safari** 打开页面；
2. 点击底部分享按钮；
3. 选择 **添加到主屏幕**。

### Android

1. 用 Chrome 打开；
2. 点击页面右上角“安装到桌面”，或浏览器菜单中的“安装应用”。

---

## data.json 结构

```json
{
  "schema_version": 1,
  "demo": false,
  "meta": {
    "data_date": "2026-11-04",
    "latest_trade_date": "2026-11-05",
    "is_stale": true,
    "stale_reason": "最新交易日 ... 尚未完整发布",
    "trading_days": 180,
    "window_start": "2026-02-05",
    "window_end": "2026-11-04",
    "missing_latest": { "shares": [], "nav": [] }
  },
  "funds": [
    {
      "code": "510300",
      "name": "华泰柏瑞沪深300ETF",
      "short_name": "华泰柏瑞",
      "exchange": "SSE",
      "manager": "华泰柏瑞基金",
      "color": "#e4572e"
    }
  ],
  "dates": ["2026-02-05", "..."],
  "series": {
    "510300": {
      "shares": [255.12, "..."],
      "nav": [4.01, "..."],
      "net_subscription": [null, 1.23, "..."],
      "market_value": [1023.45, "..."],
      "flags": [null, null, "split", "..."]
    }
  },
  "previous": {
    "date": "2026-02-04",
    "shares": { "510300": 254.9 },
    "nav": { "510300": 4.0 }
  },
  "market": {
    "date": "2026-11-04",
    "as_of": "2026-11-04T20:30:00+08:00",
    "is_stale": false,
    "total": 5360,
    "up": 3060,
    "down": 2240,
    "flat": 60,
    "limit_up": 72,
    "limit_down": 8,
    "turnover": 19876.54,
    "turnover_sh": 8500.2,
    "turnover_sz": 10500.3,
    "turnover_bj": 876.04,
    "distribution": [
      { "key": "gt10", "label": ">10%", "side": "up", "count": 38 },
      { "key": "7to10", "label": "7%~10%", "side": "up", "count": 96 },
      { "key": "3to7", "label": "3%~7%", "side": "up", "count": 486 },
      { "key": "0to3", "label": "0~3%", "side": "up", "count": 2500 },
      { "key": "0to_3", "label": "0~-3%", "side": "down", "count": 1700 },
      { "key": "_3to_7", "label": "-3%~-7%", "side": "down", "count": 420 },
      { "key": "_7to_10", "label": "-7%~-10%", "side": "down", "count": 100 },
      { "key": "lt_10", "label": "<-10%", "side": "down", "count": 20 }
    ]
  },
  "events": []
}
```

- `dates` 与 ETF 数组一一对应；缺失值为 `null`；
- `previous` 只保存窗口前一日数据，用于计算第一天净申购，不进入前端曲线；
- `market.turnover` 单位为亿元；
- 前端只 `fetch("./data.json")`，无后端接口。

---

## 常见问题

### 页面显示“无法读取 data.json”

- 确认 `data.json` 在仓库根目录，已提交到 `main`；
- 确认 GitHub Pages Source 是 `main / (root)`；
- 刚部署时等待 Pages 构建完成；
- 打开控制台看是 404 还是 JSON 解析错误。

### Actions 运行成功但没有新提交

说明数据没有变化，通常是：

- 当天不是交易日；
- 最新交易日的 ETF 份额/净值或全市场行情还没发布；
- 数据已经最新。

看日志里的 `data_date`、`大盘盘面` 即可判断。

### 大盘涨跌家数与行情软件略有差异

- 本项目按收盘涨跌幅和板块涨跌停幅度统计，排除 N/C 开头新股；
- 不含停牌、退市等无有效涨跌幅的个股；
- 不同软件对 ST、科创、北交所、新股的涨跌停处理可能不同；
- 成交额为个股成交额求和，和交易所口径可能有细微差异。

### 图表空白

- Chart.js 优先从 jsDelivr 加载，失败后尝试 unpkg；
- 两个 CDN 都不可用时，自动切换内置 Canvas 兼容渲染；
- 需要完全离线可用时，可把 `chart.umd.min.js` 放到 `vendor/`，并修改 `index.html` 的脚本引用。

### 首次回补很慢

上交所份额接口按日期查询，180 个交易日约需 180 次请求。只在首次或 `--full` 时发生；日常增量只抓最近 8 个交易日和缺失日期。

---

## 关于 Replit

抓取脚本不依赖 GitHub Actions，也可以直接在 Replit Shell 运行：

```bash
pip install -r requirements.txt
python scripts/fetch_data.py --full --output data.json
```

但 Replit 免费版的休眠、额度和定时任务限制不适合“每天 18:00 稳定无人值守”。本仓库因此采用 GitHub Actions 定时，前端仍放在 GitHub Pages。

---

## 免责声明

- 本项目仅用于个人复盘和技术学习，不构成投资建议。
- 数据来自交易所及东方财富公开接口，可能存在延迟、缺失、口径差异或接口变更。
- 净申购为根据份额变化估算的一级市场申赎金额，不等同场内资金净流入。
- 涨停/跌停家数为按涨跌幅统计的估算值，不等同交易所官方封板池。
- 请自行核对重要数据，投资决策风险自负。

## License

MIT
