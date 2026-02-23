/**
 * Side panel logic: input handling, API calls, result rendering.
 * Self-contained — no external dependencies.
 */

const $ = id => document.getElementById(id);
const KEY = 'riskfg_ext_portfolio';

// localStorage persistence
function save(positions) {
    try { localStorage.setItem(KEY, JSON.stringify(positions)); } catch (e) { }
}

function load() {
    try {
        const saved = localStorage.getItem(KEY);
        if (!saved) return;
        const positions = JSON.parse(saved);
        if (!Array.isArray(positions) || !positions.length) return;

        const list = $('pos-list');
        list.querySelectorAll('.pos-row').forEach(r => r.remove());

        positions.forEach(p => addRow(p.symbol, p.market_value));
    } catch (e) { }
}

function addRow(ticker = '', value = '') {
    const row = document.createElement('div');
    row.className = 'pos-row';
    row.innerHTML = `
        <input type="text" class="ticker" value="${ticker}" spellcheck="false">
        <input type="number" class="value" value="${value}">
        <button class="remove" title="Remove">−</button>
    `;
    $('pos-list').appendChild(row);
    row.querySelector('.remove').addEventListener('click', () => row.remove());
    if (!ticker) row.querySelector('.ticker').focus();
}

load();

// Wire remove buttons
document.querySelectorAll('.remove').forEach(btn => {
    btn.addEventListener('click', () => btn.closest('.pos-row').remove());
});

$('add-btn').addEventListener('click', () => addRow());

$('analyze-btn').addEventListener('click', async () => {
    const positions = [];
    document.querySelectorAll('.pos-row').forEach(row => {
        const ticker = row.querySelector('.ticker').value.trim().toUpperCase();
        const value = parseFloat(row.querySelector('.value').value);
        if (ticker && value > 0) positions.push({ symbol: ticker, market_value: value });
    });

    if (!positions.length) {
        showError('Add at least one ticker with a dollar value.');
        return;
    }

    save(positions);
    await analyze(positions);
});

async function analyze(positions) {
    show('loading');
    const msgs = ['Downloading factor data…', 'Fetching stock prices…', 'Running regressions…', 'Decomposing variance…'];
    let i = 0;
    const iv = setInterval(() => { if (++i < msgs.length) $('load-msg').textContent = msgs[i]; else clearInterval(iv); }, 3000);

    const base = $('api-url').value.trim().replace(/\/$/, '');

    try {
        const r = await fetch(`${base}/api/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ positions }),
        });
        clearInterval(iv);
        if (!r.ok) {
            const e = await r.json();
            throw new Error(e.detail || 'Analysis failed');
        }
        renderResults(await r.json());
    } catch (err) {
        clearInterval(iv);
        show('input');
        showError(err.message);
    }
}

function renderResults(data) {
    show('results');
    const d = data.decomposition;

    $('r-mkt').textContent = d.market_pct.toFixed(1) + '%';
    $('r-smb').textContent = d.smb_pct.toFixed(1) + '%';
    $('r-hml').textContent = d.hml_pct.toFixed(1) + '%';
    $('r-idio').textContent = d.idiosyncratic_pct.toFixed(1) + '%';
    $('r-vol').textContent = d.total_annual_vol.toFixed(1) + '%';

    // Realized vol comparison
    if (d.realized_vol != null) {
        const note = $('realized-note');
        note.classList.remove('hidden');
        note.textContent = `Model: ${d.total_annual_vol.toFixed(1)}%  |  Realized: ${d.realized_vol.toFixed(1)}%  |  Δ ${Math.abs(d.total_annual_vol - d.realized_vol).toFixed(1)}%`;
    }

    // Proportion bar
    setTimeout(() => {
        $('b-mkt').style.flexBasis = d.market_pct + '%';
        $('b-smb').style.flexBasis = d.smb_pct + '%';
        $('b-hml').style.flexBasis = d.hml_pct + '%';
        $('b-idio').style.flexBasis = d.idiosyncratic_pct + '%';
    }, 50);

    // Mini flamegraph
    renderFlamegraph(data.flamegraph);

    // Insight
    $('insight').textContent = data.insight;

    // Detail table
    const tbody = $('detail-tbody');
    tbody.innerHTML = '';
    for (const [ticker, s] of Object.entries(data.stock_details)) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${ticker}</strong></td>
            <td class="${s.beta_mkt >= 0 ? 'num-pos' : 'num-neg'}">${s.beta_mkt.toFixed(3)}</td>
            <td class="${s.beta_smb >= 0 ? 'num-pos' : 'num-neg'}">${s.beta_smb.toFixed(3)}</td>
            <td class="${s.beta_hml >= 0 ? 'num-pos' : 'num-neg'}">${s.beta_hml.toFixed(3)}</td>
            <td>${s.r_squared.toFixed(3)}</td>
            <td>${s.n_observations}</td>
        `;
        tbody.appendChild(tr);
    }
}

function renderFlamegraph(fg) {
    const container = $('flamegraph');
    container.innerHTML = '';

    if (!fg.children) return;

    // Root bar
    const rootBar = document.createElement('div');
    rootBar.className = 'fg-bar';
    rootBar.innerHTML = `<div class="fg-cell mkt" style="flex-basis:100%;background:rgba(255,255,255,0.03);color:var(--text)">${fg.name}</div>`;
    container.appendChild(rootBar);

    // Factor bars
    const factorBar = document.createElement('div');
    factorBar.className = 'fg-bar';
    fg.children.forEach(child => {
        const cls = child.factor === 'market' ? 'mkt' : child.factor === 'smb' ? 'smb' : child.factor === 'hml' ? 'hml' : 'idio';
        const cell = document.createElement('div');
        cell.className = `fg-cell ${cls}`;
        cell.style.flexBasis = child.value + '%';
        cell.textContent = `${child.name} ${child.value.toFixed(1)}%`;
        cell.title = `${child.name}: ${child.value.toFixed(1)}% of total risk`;
        factorBar.appendChild(cell);
    });
    container.appendChild(factorBar);

    // Stock bars per factor
    fg.children.forEach(child => {
        if (!child.children || !child.children.length) return;
        const cls = child.factor === 'market' ? 'mkt' : child.factor === 'smb' ? 'smb' : child.factor === 'hml' ? 'hml' : 'idio';
        const stockBar = document.createElement('div');
        stockBar.className = 'fg-bar';
        child.children.forEach(stock => {
            const cell = document.createElement('div');
            cell.className = `fg-cell ${cls}`;
            cell.style.flexBasis = stock.value + '%';
            cell.textContent = `${stock.name} ${stock.value.toFixed(1)}%`;
            cell.title = stock.meta ? `β_mkt=${stock.meta.beta_mkt.toFixed(2)} R²=${stock.meta.r_squared.toFixed(3)}` : '';
            stockBar.appendChild(cell);
        });
        container.appendChild(stockBar);
    });
}

function show(section) {
    ['input', 'loading', 'results'].forEach(s => {
        const el = $(s + '-section');
        if (el) el.classList.toggle('hidden', s !== section);
    });
    $('error-section').classList.add('hidden');
}

function showError(msg) {
    const el = $('error-section');
    el.textContent = msg;
    el.classList.remove('hidden');
}

$('back-btn').addEventListener('click', () => {
    show('input');
    ['b-mkt', 'b-smb', 'b-hml', 'b-idio'].forEach(id => { $(id).style.flexBasis = '0'; });
});
