# LSEG FX Connector

这个文件夹专门用于把 LSEG Data Library for Python 接到外汇宏观新闻交易 demo。

现在相关文件已集中在本目录：

```text
lseg_fx_connector/
  fx_macro_news_demo.py        # 外汇信号引擎
  fx_lseg_data.py              # LSEG/Refinitiv 行情和新闻适配
  fx_agent.py                  # FX Vibe Agent
  llm_report.py                # Qwen/OpenAI 兼容大模型报告
  web_app.py                   # 本地 API 服务
  static/                      # 前端页面
  fx_agent_skills/             # Vibe-Trading 风格 Agent skill
  output/                      # 信号、新闻、回测、Agent 报告和大模型报告
  lseg_ric_map.json            # RIC 配置
  policy_rates.json            # 政策利率配置
  run_web_app.sh               # 启动页面
```

`agent/examples/` 里只保留兼容 wrapper，主逻辑不再放在那里。

## Skill 设计

`fx_agent_skills/` 采用 Vibe-Trading 原生 skill 的写法：每个 skill 都有 frontmatter、适用范围、工具流程、失败条件和输出契约。

当前包含：

- `research-workflow`：把用户目标转成可追踪的 Agent 执行计划
- `lseg-fx-market-data`：LSEG/Refinitiv 行情、RIC、DXY_PROXY 和数据质量检查
- `reuters-fx-news-policy`：Reuters/LSEG 新闻、政策事件和 USD/EUR/JPY 事件分
- `fx-macro-signal-decision`：趋势、利差/政策、美元周期、新闻、风险因子合成
- `fx-agent-risk-review`：信号完整性、新闻覆盖、仓位、回测和人工复核边界
- `lseg-session-diagnostics`：诊断 Workspace/Eikon、本地代理、Python 包、RIC 和权限问题
- `dxy-proxy-construction`：直连 DXY 不可用时的 DXY_PROXY 构造和披露规则
- `fx-factor-weighting`：页面手动因子权重和交易阈值的解释与约束
- `fx-shadow-backtest`：影子回测、净值、回撤和摘要指标校验
- `fx-llm-report-writer`：Qwen/OpenAI 兼容中文报告生成边界

目标标的：

- `EUR/USD`
- `USD/JPY`
- `DXY`

输入数据：

- LSEG 历史行情：FX、DXY、VIX、10Y 收益率
- LSEG/Reuters 新闻标题
- 本地政策利率配置：Fed、ECB、BOJ

输出会写到：

`/Users/nzxkk/Desktop/vi/Vibe-Trading/lseg_fx_connector/output`

## 1. 准备 LSEG 环境

先确认这台机器能使用 LSEG：

- 已安装 LSEG Workspace / Eikon / CodeBook，或已有 LSEG Data Platform API 权限
- 当前用户已登录，并且账号有 FX、DXY、收益率、Reuters News 权限
- Python 环境安装了 `lseg-data`

安装依赖：

```bash
python -m pip install -r /Users/nzxkk/Desktop/vi/Vibe-Trading/lseg_fx_connector/requirements.txt
```

## 2. 检查 RIC 映射

默认 RIC 在：

`/Users/nzxkk/Desktop/vi/Vibe-Trading/lseg_fx_connector/lseg_ric_map.json`

如果你们账号下某个 RIC 返回空，先在 Workspace 里确认正确 RIC，再改这个 JSON。

## 3. 更新政策利率

政策利率在：

`/Users/nzxkk/Desktop/vi/Vibe-Trading/lseg_fx_connector/policy_rates.json`

示例：

```json
{
  "fed_rate": 5.25,
  "ecb_rate": 3.75,
  "boj_rate": 0.25
}
```

## 4. 跑 LSEG 版 demo

先检查 LSEG 会话：

```bash
cd /Users/nzxkk/Desktop/vi/Vibe-Trading
python lseg_fx_connector/check_lseg_session.py
```

如果看到 `localhost:9000 / 9060 connection refused`，先打开 LSEG Workspace/Eikon 并登录。

如果 `EUR=`、`JPY=` 有数据但 `.DXY` 返回空，说明 DXY 的 RIC 需要按你们账号权限调整。可以把
`lseg_fx_connector/codebook_dxy_probe.py` 里的代码复制到 CodeBook 跑一遍，找到有数的 RIC 后改
`lseg_fx_connector/lseg_ric_map.json` 里的 `DXY`。

如果所有 DXY RIC 都没有，脚本会自动用成分货币合成 DXY 代理指数。需要这些 RIC 有数据：

- `EUR=` -> EUR/USD
- `JPY=` -> USD/JPY
- `GBP=` -> GBP/USD
- `CAD=` -> USD/CAD
- `SEK=` -> USD/SEK
- `CHF=` -> USD/CHF

```bash
cd /Users/nzxkk/Desktop/vi/Vibe-Trading
./lseg_fx_connector/run_lseg_fx_demo.sh
```

指定日期：

```bash
./lseg_fx_connector/run_lseg_fx_demo.sh 2025-01-01 2026-06-10
```

## 5. 输出文件

- 最新信号：`lseg_fx_connector/output/fx_macro_news_demo_signals.csv`
- 历史信号：`lseg_fx_connector/output/fx_macro_news_demo_signal_history.csv`
- 影子回测：`lseg_fx_connector/output/fx_macro_news_demo_shadow_backtest.csv`
- 回测摘要：`lseg_fx_connector/output/fx_macro_news_demo_backtest_summary.csv`
- 中文报告：`lseg_fx_connector/output/fx_macro_news_demo_report.md`
- 可视化页面：`lseg_fx_connector/dashboard.html`

生成可视化页面：

```bash
./lseg_fx_connector/run_dashboard.sh
```

页面会读取 `lseg_fx_connector/output` 里的最新信号、影子回测和摘要文件。

## 6. 本地 Web 页面和 API

启动本地服务：

```bash
cd /Users/nzxkk/Desktop/vi/Vibe-Trading
./lseg_fx_connector/run_web_app.sh
```

浏览器打开：

```text
http://127.0.0.1:8765
```

主要 API：

- `GET /api/signals`
- `GET /api/backtest`
- `GET /api/summary`
- `GET /api/report`
- `POST /api/chat`，聊天式工作流入口；可生成策略、回测、解释信号和生成报告
- `POST /api/generate`，body 示例：`{"mode":"lseg","start":"2025-01-01","end":"2026-06-12"}`
- `POST /api/agent/run`，运行 FX Vibe Agent；它会拉真实数据、生成信号、整理步骤和中文 Agent 报告
- `GET /api/agent/latest`，读取上一次 Agent 运行结果
- `POST /api/llm-report/generate`，基于当前真实信号、新闻和回测结果生成大模型中文报告
- `GET /api/llm-report`，读取上一次大模型中文报告

本地页面只允许拉取 LSEG/Refinitiv 真实数据，不再提供离线演示数据入口。

## 7. FX Vibe Agent

页面里的 `FX Vibe Agent` 是一个轻量版 Agent，模仿 Vibe-Trading 的“目标 -> 工具 -> 信号 -> 报告”流程：

- 读取你的任务目标、日期范围和手动因子比例
- 加载本地 skill 卡片：行情数据、新闻政策、信号决策、风控检查
- 调用 LSEG/Refinitiv 拉取真实行情和 Reuters/LSEG 新闻
- 运行外汇宏观新闻信号引擎
- 把信号、影子回测、新闻覆盖整理成交易候选、观察项、风控检查和中文 Agent 报告

页面也提供 `Agent Chat`。可以直接输入：

- `生成外汇策略并回测`
- `生成 EUR/USD、USD/JPY、DXY_PROXY 策略，回测并出报告`
- `解释当前信号`
- `查看状态`
- `列出 skills`

聊天会根据当前消息、最近聊天上下文和本地输出状态选择对应 skills。每条助手回复下面会显示本次识别的 `intent` 和实际使用的 skills，方便检查它是不是按正确 workflow 执行。

聊天里的策略名称会映射为不同因子权重：

- `趋势策略`：趋势权重最高
- `利差策略` / `政策策略`：利差/政策权重最高
- `新闻策略` / `事件策略`：新闻事件权重最高
- `美元策略` / `DXY 策略`：美元周期权重最高
- `保守策略`：提高交易阈值、提高风险权重
- `激进策略`：降低交易阈值，更容易触发交易
- 未指定策略时使用 `均衡策略`

聊天也可以识别更具体的规则型策略。例如：

```text
生成外汇策略并回测：当 EUR/USD 处于长期上升趋势时，只在短期回调结束后买入；当 EUR/USD 处于长期下降趋势时，只在短期反弹结束后做空。
```

这会启用 `EUR/USD 趋势回调策略`：

- EUR/USD 使用长期 60 日均线趋势过滤
- 上升趋势中，只在短期回调动能修复时考虑买入
- 下降趋势中，只在短期反弹动能转弱时考虑做空
- USD/JPY 和 DXY_PROXY 仍使用多因子合成
- 回测使用该规则生成的历史信号，不是只改页面权重

命令行直接运行 Agent：

```bash
cd /Users/nzxkk/Desktop/vi/Vibe-Trading
./lseg_fx_connector/run_fx_agent.sh
```

Agent 输出文件：

- `lseg_fx_connector/output/fx_agent_run.json`
- `lseg_fx_connector/output/fx_agent_report.md`

当前版本是规则型 Agent，不会自动下单，也不会编造缺失数据。如果 LSEG Workspace 没打开、账号没有权限、RIC 没有数据，它会直接报错。

## 8. 大模型中文报告

大模型只负责把已经算好的信号、因子、新闻和回测摘要写成中文业务报告，不负责生成行情、新闻或交易信号。

页面默认支持 Qwen / 通义千问。使用方式：

1. 打开页面
2. 在 `API Key` 输入框粘贴 DashScope / 阿里云百炼 API Key
3. 模型默认用 `qwen-plus`
4. 点击 `生成大模型中文报告`

默认 Qwen 兼容接口：

```text
https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
```

也可以在启动服务前配置环境变量，这样页面可以不填 Key：

```bash
export DASHSCOPE_API_KEY="你的 DashScope API Key"
export FX_LLM_MODEL="qwen-plus"
```

如果使用 OpenAI 兼容接口，也可以只配置：

```bash
export OPENAI_API_KEY="你的密钥"
export FX_LLM_MODEL="你的模型名称"
```

如果你们内部接口不是 Qwen，也可以配置完整地址：

```bash
export FX_LLM_API_URL="https://你的大模型接口/v1/chat/completions"
export FX_LLM_API_KEY="你的密钥"
export FX_LLM_MODEL="你的模型名称"
```

如果你们内部接口使用 `api-key` 请求头：

```bash
export FX_LLM_AUTH_HEADER="api-key"
```

页面点击 `生成大模型中文报告` 后，会读取当前输出文件并生成：

- `lseg_fx_connector/output/fx_macro_news_llm_report.md`

## 9. 常见问题

如果报 `Missing dependency: install LSEG Data Library`：

说明当前 Python 环境没有装 `lseg-data`。

如果报 `LSEG returned no usable data`：

通常是 RIC 不对或账号没有对应数据权限。先改 `lseg_ric_map.json`。

如果新闻接口报错：

说明账号没有 Reuters News 权限，或当前 `lseg-data` 版本的新闻接口路径不同。可以先用 Workspace 导出新闻 CSV，再通过主 demo 的 `--reuters-news` 参数接入。
