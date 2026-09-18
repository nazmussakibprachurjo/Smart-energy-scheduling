const $ = (selector) => document.querySelector(selector);
const state = { cases: [], lastResponse: null, apiKeyConfigured: false };

const sampleSelect = $('#sampleSelect');
const editor = $('#scenarioJson');
const optimizeButton = $('#optimizeButton');
const inputHint = $('#inputHint');

async function boot() {
  await Promise.all([checkSystem(), loadCases()]);
  sampleSelect.addEventListener('change', selectCase);
  $('#resetButton').addEventListener('click', reset);
  optimizeButton.addEventListener('click', optimize);
  $('#downloadButton').addEventListener('click', downloadResult);
  editor.addEventListener('input', validateEditor);
}

async function checkSystem() {
  const dot = $('#statusDot');
  try {
    const [health, config] = await Promise.all([fetch('/health'), fetch('/app-config')]);
    if (!health.ok || !config.ok) throw new Error('unavailable');
    const settings = await config.json();
    state.apiKeyConfigured = settings.api_key_configured;
    dot.classList.add(settings.api_key_configured ? 'ok' : 'bad');
    $('#systemStatus').textContent = settings.api_key_configured ? 'System ready' : 'Reference preview';
    $('#modelName').textContent = `${settings.provider} / ${settings.model}`;
    updateActionLabel();
  } catch {
    dot.classList.add('bad');
    $('#systemStatus').textContent = 'System unavailable';
  }
}

async function loadCases() {
  try {
    const response = await fetch('/static/data/public_cases.json');
    const payload = await response.json();
    state.cases = payload.cases;
    sampleSelect.innerHTML = state.cases.map((item, index) =>
      `<option value="${index}">${item.id} — ${escapeHtml(item.label)}</option>`
    ).join('');
    sampleSelect.value = '0';
    selectCase();
  } catch {
    sampleSelect.innerHTML = '<option value="">Cases unavailable</option>';
    showToast('Could not load the public sample pack.', true);
  }
}

function selectCase() {
  const item = state.cases[Number(sampleSelect.value)];
  if (!item) return;
  editor.value = JSON.stringify(item.input, null, 2);
  validateEditor();
  updateActionLabel();
}

function reset() {
  sampleSelect.value = '0';
  selectCase();
  state.lastResponse = null;
  $('#results').classList.add('hidden');
  $('#emptyState').classList.remove('hidden');
}

function validateEditor() {
  try {
    const value = JSON.parse(editor.value);
    const valid = value && value.scenario_id && Array.isArray(value.hours) && value.hours.length === 24;
    if (!valid) throw new Error();
    inputHint.textContent = `${value.scenario_id} • ${value.operator_notes?.length || 0} operator note(s) • 24 hourly records`;
    inputHint.classList.remove('error');
    optimizeButton.disabled = false;
    updateActionLabel();
    return value;
  } catch {
    inputHint.textContent = 'JSON is incomplete or invalid.';
    inputHint.classList.add('error');
    optimizeButton.disabled = true;
    return null;
  }
}

async function optimize() {
  const scenario = validateEditor();
  if (!scenario) return;
  if (!state.apiKeyConfigured) {
    const selected = state.cases[Number(sampleSelect.value)];
    if (selected && JSON.stringify(scenario) === JSON.stringify(selected.input)) {
      state.lastResponse = selected.expected_output;
      render(selected.expected_output);
      showToast('Showing the official public reference plan. Configure the selected LLM provider for live interpretation.');
      return;
    }
    showToast('Live interpretation requires the selected provider API key. Choose an unchanged public sample for reference preview.', true);
    return;
  }
  setBusy(true);
  try {
    const response = await fetch('/optimize-energy', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(scenario)
    });
    let payload;
    try { payload = await response.json(); } catch { payload = {}; }
    if (!response.ok) {
      const detail = typeof payload.detail === 'string' ? payload.detail : 'Request validation failed.';
      throw new Error(detail);
    }
    state.lastResponse = payload;
    render(payload);
    showToast(`Optimal plan generated for ${payload.scenario_id}.`);
  } catch (error) {
    showToast(error.message || 'Unable to generate the plan.', true);
  } finally { setBusy(false); }
}

function setBusy(busy) {
  optimizeButton.disabled = busy;
  optimizeButton.querySelector('span').textContent = busy ? 'Interpreting and optimizing…' : actionLabel();
}

function actionLabel() {
  return state.apiKeyConfigured ? 'Generate optimal plan' : 'Preview reference plan';
}

function updateActionLabel() {
  if (!optimizeButton.disabled) optimizeButton.querySelector('span').textContent = actionLabel();
}

function render(data) {
  $('#emptyState').classList.add('hidden');
  $('#results').classList.remove('hidden');
  $('#totalCost').textContent = Number(data.total_cost_bdt).toLocaleString(undefined,{maximumFractionDigits:2});
  $('#totalGrid').textContent = Number(data.total_grid_kwh).toLocaleString(undefined,{maximumFractionDigits:2});
  $('#peakGrid').textContent = Number(data.peak_grid_kwh).toLocaleString(undefined,{maximumFractionDigits:2});
  $('#directiveCount').textContent = data.directive_interpretation.filter(d => d.applies).length;
  $('#planSummary').textContent = data.plan_summary;
  renderChart(data.hourly_plan);
  $('#directives').innerHTML = data.directive_interpretation.map((d) => `
    <div class="directive">
      <span class="directive-index">${String(d.note_index + 1).padStart(2,'0')}</span>
      <div><strong>${escapeHtml(d.directive_type.replaceAll('_',' '))}</strong><p>${escapeHtml(d.explanation)}</p>
      <code>${d.structured_adjustment ? escapeHtml(JSON.stringify(d.structured_adjustment)) : 'No schedule adjustment'}</code></div>
    </div>`).join('');
  $('#scheduleBody').innerHTML = data.hourly_plan.map(p => `
    <tr><td>${String(p.hour).padStart(2,'0')}:00</td><td>${fmt(p.grid_kwh)}</td><td>${fmt(p.solar_used_kwh)}</td>
    <td><span class="action ${p.battery_action}">${p.battery_action}</span></td><td>${fmt(p.battery_kwh)}</td><td>${fmt(p.battery_energy_after_kwh)}</td></tr>`).join('');
  $('#results').scrollIntoView({behavior:'smooth',block:'start'});
}

function renderChart(plan) {
  const max = Math.max(...plan.flatMap(p => [p.grid_kwh, p.solar_used_kwh, p.battery_kwh]), 1);
  $('#energyChart').innerHTML = plan.map((p, i) => `
    <div class="bar-group" title="Hour ${i}: grid ${fmt(p.grid_kwh)}, solar ${fmt(p.solar_used_kwh)}, battery ${fmt(p.battery_kwh)}">
      <span class="bar grid" style="height:${p.grid_kwh/max*100}%"></span>
      <span class="bar solar" style="height:${p.solar_used_kwh/max*100}%"></span>
      <span class="bar battery" style="height:${p.battery_kwh/max*100}%"></span>
      <label>${i}</label>
    </div>`).join('');
}

function downloadResult() {
  if (!state.lastResponse) return;
  const blob = new Blob([JSON.stringify(state.lastResponse,null,2)],{type:'application/json'});
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `${state.lastResponse.scenario_id}-gridwise-plan.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function showToast(message, error=false) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.toggle('error', error);
  toast.classList.add('show');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove('show'), 3800);
}
function fmt(value) { return Number(value).toLocaleString(undefined,{maximumFractionDigits:2}); }
function escapeHtml(value) { const node=document.createElement('div'); node.textContent=String(value); return node.innerHTML; }
document.addEventListener('DOMContentLoaded', boot);
