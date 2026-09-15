# 金融市场动态日历 Finance Calendar

一个无需服务器、数据库或付费 API Key 的开源 ICS 日历生成器。它从官方发布日程和可用的免费金融数据源更新事件，通过 GitHub Actions 每天运行两次，并把 `dist/` 发布到 GitHub Pages。

生成四个可独立订阅的日历：

| 文件 | 内容 |
| --- | --- |
| `macro.ics` | 美国重要宏观数据、FOMC、初请失业金、ISM PMI |
| `earnings.ics` | `config.yaml` 中的自选股财报 |
| `market.ics` | NYSE 休市、提前收市、美股四巫日 |
| `all.ics` | 上述三个日历的去重合并 |

项目重点不是堆积指标，而是保证核心事件、稳定 UID、时区/DST 和单个数据源故障时的可用性。

## 一分钟部署

### 方案 A：Fork

1. Fork 本仓库。
2. 打开 `config.yaml`，修改 `stocks` 和开关后提交。
3. 在仓库的 **Actions** 页面启用工作流；Fork 的定时工作流默认可能是关闭的。
4. 打开 **Settings → Actions → General → Workflow permissions**，选择 **Read and write permissions**。
5. 打开 **Settings → Pages → Build and deployment → Source**，选择 **GitHub Actions**。
6. 在 **Actions → Update finance calendar → Run workflow** 手动执行一次。
7. 等待 `update` 和 `deploy` 两个 job 都变绿，然后复制订阅地址。

假设 GitHub 用户名是 `USERNAME`，仓库名是 `finance-calendar`：

```text
https://USERNAME.github.io/finance-calendar/macro.ics
https://USERNAME.github.io/finance-calendar/earnings.ics
https://USERNAME.github.io/finance-calendar/market.ics
https://USERNAME.github.io/finance-calendar/all.ics
```

如果仓库改了名字，URL 中也要使用实际仓库名。GitHub Pages 首次发布通常需要短暂等待。

### 方案 B：创建全新 GitHub 仓库

在 GitHub 新建一个空的公开仓库 `finance-calendar`，不要预先添加 README 或 License。进入本项目目录后执行：

```bash
git init
git add .
git commit -m "feat: initialize finance calendar"
git branch -M main
git remote add origin https://github.com/USERNAME/finance-calendar.git
git push -u origin main
```

然后按方案 A 的第 4～7 步开启 Actions 和 Pages。项目不会自行创建、提交或推送你的远程仓库。

## 订阅 Apple Calendar

必须选择“订阅日历”，不要先下载 ICS 再导入。导入得到的是静态副本，GitHub Actions 后续更新不会同步。

### iPhone / iPad

1. 复制某个 `https://.../*.ics` 地址。
2. 打开 **设置 → App → 日历 → 日历账户 → 添加账户 → 其他 → 添加已订阅的日历**。不同 iOS/iPadOS 版本的菜单名称可能略有差异。
3. 粘贴 URL，点“下一步”，确认后保存。

也可以在“日历”App 的日历列表中寻找“添加订阅日历”入口。

### macOS

1. 打开“日历”App。
2. 选择 **文件 → 新建日历订阅**。
3. 粘贴 ICS URL，设置名称和自动刷新频率后确认。

Apple 决定远程订阅的实际刷新时间；工作流每日运行两次，不代表每台设备也会恰好每 12 小时刷新。

### Google Calendar / Outlook

- Google Calendar：网页左侧“其他日历”旁的 `+` →“通过网址”→ 粘贴 ICS URL。
- Outlook 网页版：“添加日历”→“从 Web 订阅”→ 粘贴 ICS URL。

同样应使用 URL 订阅，而不是下载后导入。

## 配置

日常使用只需修改 `config.yaml`：

```yaml
timezone: Asia/Shanghai
calendar_name: 金融市场动态
lookahead_days: 400
history_days: 30
request_timeout_seconds: 30
claims_weeks_ahead: 16

stocks:
  - NVDA
  - MU
  - AMD

macro:
  nfp: true
  unemployment: true
  jobless_claims: true
  cpi: true
  core_cpi: true
  ppi: true
  core_ppi: true
  pce: true
  core_pce: true
  gdp: true
  retail_sales: true
  ism_manufacturing: true
  ism_services: true
  fomc: true
  fomc_minutes: true

market:
  holidays: true
  early_close: true
  quadruple_witching: true
```

- `timezone` 必须是 IANA 时区名，例如 `Asia/Shanghai`、`America/New_York`。
- 股票代码会转成大写并去重。
- `history_days` 防止刚发生的事件立即从订阅中消失。
- `lookahead_days` 最大支持 1095 天，但数据源未必会提前公布这么远。

## 本地运行

需要 Python 3.11 或更高版本：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
python -m src.main
python -m src.validate dist
```

只测试缓存回退、不访问远程服务：

```bash
python -m src.main --offline
```

指定可复现日期：

```bash
python -m src.main --today 2026-09-15 --offline
```

## 数据源与选择原因

| 事件 | 实际来源 | 原因与回退 |
| --- | --- | --- |
| NFP、失业率、CPI/Core CPI、PPI/Core PPI | [BLS 官方在线日历](https://www.bls.gov/schedule/news_release/bls.ics) | 一手来源，包含官方日期和 Eastern Time。BLS 拒绝自动请求时，改读 [FRED Release Calendar](https://fred.stlouisfed.org/releases/calendar)；FRED 明确说明日期由数据发布方提供。两者失败则保留 BLS 范围的旧缓存。 |
| PCE/Core PCE、GDP | [BEA Release Schedule](https://www.bea.gov/news/schedule) | BEA 官方发布日程，直接给出日期、时间和参考期。 |
| Retail Sales | [U.S. Census Bureau Release Schedule](https://www.census.gov/retail/release_schedule.html) | Census 官方 Advance Monthly Retail Trade 日程。 |
| FOMC 会议、利率决议、纪要 | [Federal Reserve FOMC Calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) | 会议日期来自美联储。未正式列出纪要发布日期时，按美联储公布的“通常在决议后三周发布”政策生成，并在 Description 标明方法。 |
| ISM Manufacturing / Services PMI | [ISM Report Release Calendar](https://www.ismworld.org/supply-management-news-and-reports/reports/rob-report-calendar/) | 优先解析 ISM 官方年度表；验证码或结构变化导致失败时，按 ISM 公布的第一/第三个工作日规则生成，并输出 warning。 |
| Initial Jobless Claims | [U.S. Department of Labor ETA](https://www.dol.gov/newsroom/releases/eta) | DOL 没有稳定的未来日期机器接口。当前按其正常周四 08:30 ET 发布惯例生成，周四为联邦假日时前移一天；属于“规则生成”，不是逐期官方确认。 |
| 自选股财报 | [Yahoo Finance](https://finance.yahoo.com/) via `yfinance` | 免费、无需 Key，适合逐股票更新日期、公司名及可得的 EPS/营收预估；每个股票独立失败和回退。 |
| NYSE 休市与提前收市 | [`pandas-market-calendars`](https://github.com/rsheftel/pandas_market_calendars) 的 NYSE calendar | 库包含 NYSE 节假日、observed holiday 和 special close 规则；事件 Description 链接 [NYSE Hours & Calendars](https://www.nyse.com/markets/hours-calendars) 便于复核。 |
| 四巫日 | 季度规则 | 计算 3、6、9、12 月第三个星期五，稳定且无需外部 API。 |

## 缓存与故障策略

`data/macro.json`、`data/earnings.json`、`data/market.json` 是需要提交到 Git 的最近成功快照：

1. 每个来源、每个股票都有独立 `scope`。
2. 某个 scope 成功时，只替换该 scope 的旧事件。
3. 某个 scope 失败时，保留该 scope 的缓存；其他成功来源继续更新。
4. 只有事件内容改变时才更新缓存时间，因此 `DTSTAMP` 不会让每次运行都产生无意义 diff。
5. Actions 只在 `data/` 或 `dist/` 真正变化时创建 `chore: update finance calendar` commit。

首次部署已经带有一份可用快照。不要把 `data/*.json` 加入 `.gitignore`，否则临时数据源故障时无法可靠回退。

## ICS 与 UID 设计

- 使用 `icalendar` 生成 RFC 5545 内容，并用独立校验器回读。
- 所有定时事件先以 `America/New_York` 建模，再写成 UTC；EST/EDT 切换由 IANA 时区数据库处理，不固定写成北京时间 20:30 或 21:30。
- 只有日期的数据写成 `VALUE=DATE` 全天事件，`DTEND` 按 RFC 5545 使用排他结束日期。
- 宏观 UID 使用指标和参考期，例如 `macro-US-CPI-2026-09@finance-calendar`。
- 财报 UID 首次使用股票和季度，后续抓取会把新日期与旧缓存配对并复用 UID；日期调整不会在 Apple Calendar 中创建重复事件。
- `all.ics` 按 UID 去重；校验器要求它的 UID 集合与三个子日历的并集完全一致。

## GitHub Pages 与 MIME / 缓存

工作流通过 GitHub 官方 Pages Actions 直接发布 `dist/`，并包含 `.nojekyll`。发布后可以检查响应：

```bash
curl -I https://USERNAME.github.io/finance-calendar/all.ics
```

GitHub Pages 通常会为 `.ics` 返回可用的静态文件响应。即使服务端内容已更新，Apple Calendar、Google Calendar 和 Outlook 仍可能按自己的缓存周期延迟刷新；项目无法强制客户端立即拉取。URL 必须保持不变。

## 已知限制

1. BLS 和 ISM 可能按 IP、频率或验证码阻止 GitHub runner；已有 FRED/规则降级与缓存，但应定期查看 Actions warning。
2. 初请失业金的未来日期是按官方发布惯例生成，临时改期可能在下一次人工/数据源确认前不准确。
3. Yahoo/Nasdaq 展示的财报日期常是基于历史规律的预计日期，并非公司 IR 的最终承诺；项目每天重抓并保留稳定 UID。Yahoo 未提供可靠时段时使用全天 `[TAS]`。
4. Yahoo 当前接口不总是返回 fiscal quarter。缺失时 Description 会明确标记为按财报日期推导的 calendar-quarter fallback，不冒充公司财季。
5. `pandas-market-calendars` 是随 Python 包发布的规则库，不是 NYSE 实时 API。交易所临时停市需要库更新或手工修正。
6. FOMC 决议按常规 14:00 ET、纪要按常规 14:00 ET 建模；临时会议或特别公告不在当前版本自动抓取范围内。
7. Jackson Hole 与 Powell 讲话没有稳定且结构统一的官方未来日程接口，第一版没有加入，以避免低可信事件。
8. 受保护的默认分支可能拒绝 Actions 自动 push。此时需允许 `github-actions[bot]` 写入，或自行把更新改造成 PR 流程。

这些日历仅用于信息提醒，不构成投资建议或交易所正式交易安排。重要交易决策应再次核对原始来源。

## 扩展新市场或事件

代码按职责拆分：

```text
src/
├── main.py                 # 编排、缓存、输出
├── calendar.py             # RFC 5545 序列化
├── config.py               # 配置校验
├── providers/
│   ├── macro.py            # 宏观来源编排
│   ├── bls.py / bea.py ... # 独立官方来源解析器
│   ├── earnings.py         # 财报及稳定 UID 对账
│   └── market.py           # NYSE 与四巫日
└── utils/                  # HTTP、缓存、时区
```

新增港股、央行、IPO、拆股、指数调仓或期权到期时，新增 provider 和独立 scope，再由 `main.py` 合并即可，不需要把逻辑塞进单一文件。

## License

[MIT](LICENSE)
