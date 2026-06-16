const state = {
  signals: [],
  summary: [],
  backtest: [],
  news: [],
  report: '',
  agent: {},
  skills: [],
  llmReport: '',
  chat: [
    {
      role: 'assistant',
      text: '你可以直接说：“生成外汇策略并回测”、“趋势回调策略”、“生成中文报告”或“解释当前信号”。'
    }
  ]
};

const fmtNum = (value, digits = 2) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return 'N/A';
  return n.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
};

const fmtPct = value => {
  const n = Number(value);
  if (!Number.isFinite(n)) return 'N/A';
  return `${(n * 100).toFixed(2)}%`;
};

const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
})[char]);

const setStatus = text => {
  document.getElementById('statusBox').textContent = text;
};

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const data = await res.json();
  if (!res.ok || data.status === 'error') {
    const failedStep = data?.result?.steps?.find(step => step.status === 'error');
    const message = failedStep?.error || data?.result?.stderr || data?.message || '请求失败';
    throw new Error(message);
  }
  return data;
}

async function loadAll() {
  const [signals, summary, backtest, report, news, agent, skills, llmReport] = await Promise.all([
    api('/api/signals'),
    api('/api/summary'),
    api('/api/backtest'),
    api('/api/report'),
    api('/api/news'),
    api('/api/agent/latest'),
    api('/api/skills'),
    api('/api/llm-report')
  ]);
  state.signals = signals.data || [];
  state.summary = summary.data || [];
  state.backtest = backtest.data || [];
  state.news = news.data || [];
  state.report = report.markdown || '';
  state.agent = agent.data || {};
  state.skills = skills.data || [];
  state.llmReport = llmReport.markdown || '';
  render();
}

function render() {
  updateStrategyControls();
  renderMetrics();
  renderSignals();
  renderFactors();
  renderChart();
  renderChat();
  renderAgent();
  renderLlmReport();
  document.getElementById('report').textContent = state.report || '暂无报告。';
}

function renderMetrics() {
  const row = state.summary[0] || {};
  const metrics = [
    ['总收益', fmtPct(row.total_return || 0)],
    ['最大回撤', fmtPct(row.max_drawdown || 0)],
    ['Sharpe', fmtNum(row.sharpe || 0, 2)],
    ['有持仓天数', String(row.active_days || 0)]
  ];
  document.getElementById('metrics').innerHTML = metrics.map(([label, value]) => `
    <div class="metric"><span>${label}</span><strong>${value}</strong></div>
  `).join('');
}

function renderSignals() {
  const box = document.getElementById('signals');
  if (!state.signals.length) {
    box.innerHTML = '<div class="empty">暂无信号。请先运行 Agent。</div>';
    document.getElementById('asOf').textContent = '';
    return;
  }
  document.getElementById('asOf').textContent = `信号日期：${state.signals[0].as_of || 'N/A'}`;
  box.innerHTML = state.signals.map(row => {
    const sideValue = String(row.side || 'HOLD').toUpperCase();
    const side = ['LONG', 'SHORT', 'HOLD'].includes(sideValue) ? sideValue.toLowerCase() : 'hold';
    const reason = row.rationale || row.signal_state || '暂无原因说明';
    return `
      <article class="signal-card ${side}">
        <div class="signal-top">
          <span class="instrument">${escapeHtml(row.instrument || '')}</span>
          <span class="side">${escapeHtml(sideValue)}</span>
        </div>
        <div class="price">${fmtNum(row.close, row.instrument === 'USD/JPY' ? 3 : 4)}</div>
        <div class="card-grid">
          <div><span>权重</span><strong>${fmtNum(row.target_weight || 0, 2)}</strong></div>
          <div><span>置信度</span><strong>${fmtNum(row.confidence || Math.abs(row.composite_score || 0), 2)}</strong></div>
          <div><span>分数</span><strong>${fmtNum(row.composite_score || 0, 2)}</strong></div>
        </div>
        <div class="reason">${escapeHtml(reason)}</div>
      </article>
    `;
  }).join('');
}

function renderFactors() {
  const rows = state.signals.map(row => `
    <tr>
      <td>${escapeHtml(row.instrument || '')}</td>
      <td>${fmtNum(row.trend_score || 0, 2)}</td>
      <td>${fmtNum(row.carry_policy_score || 0, 2)}</td>
      <td>${fmtNum(row.dxy_cycle_score || 0, 2)}</td>
      <td>${fmtNum(row.news_policy_score || 0, 2)}</td>
      <td>${fmtNum(row.risk_sentiment_score || 0, 2)}</td>
    </tr>
  `).join('');
  document.getElementById('factorRows').innerHTML = rows || '<tr><td colspan="6">暂无因子明细</td></tr>';
}

function renderChart() {
  const svg = document.getElementById('equityChart');
  svg.innerHTML = '';
  const values = state.backtest.map(row => Number(row.equity)).filter(Number.isFinite);
  const width = 760;
  const height = 220;
  const axis = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  axis.setAttribute('x1', '0');
  axis.setAttribute('y1', String(height - 12));
  axis.setAttribute('x2', String(width));
  axis.setAttribute('y2', String(height - 12));
  axis.setAttribute('class', 'axis');
  svg.appendChild(axis);
  if (!values.length) return;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1e-9);
  const step = width / Math.max(values.length - 1, 1);
  const points = values.map((value, index) => {
    const x = index * step;
    const y = height - (((value - min) / span) * (height - 24) + 12);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(' ');
  const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
  line.setAttribute('points', points);
  line.setAttribute('class', 'equity-line');
  svg.appendChild(line);
}

function renderChat() {
  const box = document.getElementById('chatMessages');
  box.innerHTML = state.chat.map(message => `
    <div class="chat-message ${message.role}">
      <div>${escapeHtml(message.text || '')}</div>
      ${message.intent ? `<div class="chat-intent">intent: ${escapeHtml(message.intent)}</div>` : ''}
      ${message.strategy ? `<div class="chat-intent">strategy: ${escapeHtml(message.strategy)}</div>` : ''}
      ${message.router ? `<div class="chat-intent">router: ${escapeHtml(message.router)}</div>` : ''}
      ${message.skills?.length ? `
        <div class="chat-skill-row">
          ${message.skills.map(skill => `
            <span class="chat-skill">${escapeHtml(skill.name || '')}</span>
          `).join('')}
        </div>
      ` : ''}
      ${message.skillReasoning ? `<div class="chat-reason">${escapeHtml(message.skillReasoning)}</div>` : ''}
    </div>
  `).join('');
  box.scrollTop = box.scrollHeight;
}

function currentPayload() {
  return {
    start: document.getElementById('startInput').value,
    end: document.getElementById('endInput').value,
    trendWeight: Number(document.getElementById('trendWeight').value),
    carryWeight: Number(document.getElementById('carryWeight').value),
    dollarWeight: Number(document.getElementById('dollarWeight').value),
    newsWeight: Number(document.getElementById('newsWeight').value),
    riskWeight: Number(document.getElementById('riskWeight').value),
    scoreThreshold: Number(document.getElementById('scoreThreshold').value),
    ruleStrategy: document.getElementById('ruleStrategy').value,
    newsScoreMode: document.getElementById('newsScoreMode').value
  };
}

function currentObjective() {
  const rule = document.getElementById('ruleStrategy').value;
  const newsMode = document.getElementById('newsScoreMode').value;
  const strategyText = rule === 'eurusd_trend_pullback'
    ? '使用 EUR/USD 趋势回调策略，并监控 USD/JPY 和 DXY_PROXY 的多因子外汇信号'
    : '监控 EUR/USD、USD/JPY 和 DXY_PROXY 的多因子外汇信号';
  const newsText = newsMode === 'llm'
    ? '新闻由大模型读取 Reuters/LSEG 新闻后判断正负面分数'
    : '新闻由本地规则读取 Reuters/LSEG 新闻后判断正负面分数';
  return `${strategyText}，结合 LSEG 行情、Reuters/LSEG 新闻、宏观政策和风险情绪，生成今天的交易信号、影子回测和是否值得交易的解释；${newsText}。`;
}

function renderAgent() {
  const stepsBox = document.getElementById('agentSteps');
  const skillPlanBox = document.getElementById('skillPlan');
  const reportBox = document.getElementById('agentReport');
  const decisionsBox = document.getElementById('agentDecisions');
  const riskBox = document.getElementById('agentRiskChecks');
  const agent = state.agent || {};
  const steps = agent.steps || [];
  const skillPlan = agent.skill_plan || [];
  const decisions = agent.decisions || [];
  const riskChecks = agent.risk_checks || [];
  skillPlanBox.innerHTML = skillPlan.length ? skillPlan.map(item => `
    <article class="skill-card ${item.available ? 'available' : 'missing'}">
      <div class="skill-top">
        <strong>${escapeHtml(item.step || '')}</strong>
        <span>${escapeHtml(item.category || '')}</span>
      </div>
      <h3>${escapeHtml(item.title || item.skill || '')}</h3>
      <p>${escapeHtml(item.purpose || '')}</p>
    </article>
  `).join('') : '<div class="empty">Agent 尚未生成 skill 执行计划。</div>';
  stepsBox.innerHTML = steps.length ? steps.map(step => `
    <div class="agent-step ${step.status}">
      <strong>${escapeHtml(step.name || '')}</strong>
      <span>${step.status === 'ok' ? '完成' : '失败'}</span>
      <p>${escapeHtml(step.description || '')}</p>
    </div>
  `).join('') : '<div class="empty">Agent 尚未运行。</div>';
  decisionsBox.innerHTML = decisions.length ? decisions.map(item => `
    <article class="decision-item">
      <div class="decision-top">
        <strong>${escapeHtml(item.instrument || '')}</strong>
        <span>${escapeHtml(item.decision || '')}</span>
      </div>
      <div class="decision-meta">
        <span>${escapeHtml(item.side || 'HOLD')}</span>
        <span>分数 ${fmtNum(item.score || 0, 2)}</span>
        <span>权重 ${fmtNum(item.target_weight || 0, 2)}</span>
      </div>
      <p>${escapeHtml(item.action || '')}：${escapeHtml(item.reason || '')}</p>
    </article>
  `).join('') : '<div class="empty">暂无 Agent 决策。</div>';
  riskBox.innerHTML = riskChecks.length ? riskChecks.map(item => `
    <div class="risk-item ${item.status === '未通过' ? 'fail' : item.status === '关注' ? 'watch' : 'pass'}">
      <strong>${escapeHtml(item.name || '')}</strong>
      <span>${escapeHtml(item.status || '')}</span>
      <p>${escapeHtml(item.message || '')}</p>
    </div>
  `).join('') : '<div class="empty">暂无风控检查。</div>';
  reportBox.textContent = agent.report || '暂无 Agent 报告。';
}

function renderLlmReport() {
  document.getElementById('llmReport').textContent = state.llmReport || '暂无大模型报告。';
}

function updateStrategyControls() {
  const rule = document.getElementById('ruleStrategy').value;
  const isPullback = rule === 'eurusd_trend_pullback';
  const newsMode = document.getElementById('newsScoreMode').value;
  document.getElementById('factorControls').hidden = isPullback;
  document.getElementById('pullbackControls').hidden = !isPullback;
  document.getElementById('strategyModeText').textContent = isPullback ? 'EUR/USD 趋势回调' : '多因子合成';
  const newsText = newsMode === 'llm' ? '新闻由大模型评分，需要填写 Qwen/OpenAI API Key。' : '新闻由本地关键词规则评分。';
  document.getElementById('strategySummary').textContent = (isPullback
    ? 'EUR/USD 使用长期趋势过滤和短期回调/反弹结束规则，不再由百分比权重决定方向。'
    : '趋势、利差/政策、美元周期、新闻和风险按比例合成一个交易分数。') + newsText;
}

function getLlmPayload() {
  return {
    llmProvider: document.getElementById('llmProvider').value,
    llmApiKey: document.getElementById('llmApiKey').value.trim(),
    llmModel: document.getElementById('llmModel').value.trim(),
    llmApiUrl: document.getElementById('llmApiUrl').value.trim()
  };
}

function currentChatPayload(message) {
  return {
    ...currentPayload(),
    ...getLlmPayload(),
    objective: currentObjective(),
    message,
    chatHistory: state.chat.slice(-10).map(item => ({
      role: item.role,
      text: item.text,
      intent: item.intent || ''
    }))
  };
}

function applyLlmProviderDefaults() {
  const provider = document.getElementById('llmProvider').value;
  const modelInput = document.getElementById('llmModel');
  const apiUrlInput = document.getElementById('llmApiUrl');
  if (provider === 'qwen') {
    modelInput.value = modelInput.value || 'qwen-plus';
    apiUrlInput.value = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions';
  }
  if (provider === 'openai' && apiUrlInput.value.includes('dashscope.aliyuncs.com')) {
    apiUrlInput.value = 'https://api.openai.com/v1/chat/completions';
    modelInput.value = '';
  }
}

function applyStrategyProfile(profile) {
  if (!profile) return;
  const mapping = {
    trendWeight: 'trendWeight',
    carryWeight: 'carryWeight',
    dollarWeight: 'dollarWeight',
    newsWeight: 'newsWeight',
    riskWeight: 'riskWeight',
    scoreThreshold: 'scoreThreshold',
    ruleStrategy: 'ruleStrategy'
  };
  Object.entries(mapping).forEach(([key, id]) => {
    const input = document.getElementById(id);
    if (input && profile[key] !== undefined) input.value = profile[key];
  });
  updateStrategyControls();
}

async function runAgent() {
  const buttons = Array.from(document.querySelectorAll('button'));
  buttons.forEach(btn => { btn.disabled = true; });
  try {
    setStatus('Agent 正在更新行情、新闻、信号和回测...');
    const result = await api('/api/agent/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...currentPayload(),
        ...getLlmPayload(),
        objective: currentObjective()
      })
    });
    state.agent = result.result || {};
    await loadAll();
    setStatus(state.agent.ok ? 'Agent 已完成' : 'Agent 运行失败，已生成错误报告');
  } catch (err) {
    setStatus(`Agent 失败：${err.message.slice(0, 260)}`);
  } finally {
    buttons.forEach(btn => { btn.disabled = false; });
  }
}

async function generateLlmReport() {
  const buttons = Array.from(document.querySelectorAll('button'));
  buttons.forEach(btn => { btn.disabled = true; });
  try {
    setStatus('正在基于当前结果生成中文报告...');
    const result = await api('/api/llm-report/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        objective: currentObjective(),
        ...getLlmPayload()
      })
    });
    state.llmReport = result.result?.report || '';
    renderLlmReport();
    setStatus('中文报告已生成');
  } catch (err) {
    setStatus(`大模型报告失败：${err.message.slice(0, 260)}`);
  } finally {
    buttons.forEach(btn => { btn.disabled = false; });
  }
}

async function sendChatMessage(text) {
  const message = (text || document.getElementById('chatInput').value).trim();
  if (!message) return;
  document.getElementById('chatInput').value = '';
  state.chat.push({ role: 'user', text: message });
  renderChat();
  const buttons = Array.from(document.querySelectorAll('button'));
  buttons.forEach(btn => { btn.disabled = true; });
  try {
    setStatus('Agent Chat 正在处理...');
    const response = await api('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentChatPayload(message))
    });
    const result = response.result || {};
    state.chat.push({
      role: 'assistant',
      text: result.reply || '已处理。',
      intent: result.intent || '',
      strategy: result.strategy_profile?.label || '',
      router: result.skill_router || '',
      skills: result.used_skills || [],
      skillReasoning: result.skill_reasoning || ''
    });
    if (result.agent) state.agent = result.agent;
    if (result.strategy_profile) applyStrategyProfile(result.strategy_profile);
    if (result.llm_report) state.llmReport = result.llm_report.report || '';
    if (result.refresh) await loadAll();
    renderChat();
    setStatus('Agent Chat 已完成');
  } catch (err) {
    state.chat.push({ role: 'assistant', text: `失败：${err.message.slice(0, 500)}` });
    renderChat();
    setStatus(`Agent Chat 失败：${err.message.slice(0, 260)}`);
  } finally {
    buttons.forEach(btn => { btn.disabled = false; });
  }
}

document.getElementById('refreshBtn').addEventListener('click', async () => {
  try {
    await loadAll();
    setStatus('已刷新');
  } catch (err) {
    setStatus(`刷新失败：${err.message}`);
  }
});

document.getElementById('agentBtn').addEventListener('click', runAgent);
document.getElementById('llmReportBtn').addEventListener('click', generateLlmReport);
document.getElementById('llmProvider').addEventListener('change', applyLlmProviderDefaults);
document.getElementById('ruleStrategy').addEventListener('change', updateStrategyControls);
document.getElementById('newsScoreMode').addEventListener('change', updateStrategyControls);
document.getElementById('chatSendBtn').addEventListener('click', () => sendChatMessage());
document.getElementById('chatInput').addEventListener('keydown', event => {
  if (event.key === 'Enter') sendChatMessage();
});
document.querySelectorAll('[data-chat]').forEach(button => {
  button.addEventListener('click', () => sendChatMessage(button.dataset.chat));
});

document.getElementById('endInput').value = new Date().toISOString().slice(0, 10);
applyLlmProviderDefaults();
loadAll().then(() => setStatus('已加载本地输出')).catch(err => setStatus(`加载失败：${err.message}`));
