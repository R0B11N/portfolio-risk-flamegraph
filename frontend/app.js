/**
 * Application logic: input handling, API calls, result rendering.
 */

const API_BASE = 'http://localhost:8000';
let flamegraph = null;
let csvPositions = null;

const $ = id => document.getElementById(id);
const sections = {
    input: $('input-section'),
    loading: $('loading-section'),
    results: $('results-section'),
};

// ── localStorage Persistence ──
function savePortfolio(positions) {
    try { localStorage.setItem('riskfg_portfolio', JSON.stringify(positions)); } catch (e) { /* noop */ }
}

function loadSavedPortfolio() {
    try {
        const saved = localStorage.getItem('riskfg_portfolio');
        if (!saved) return;
        const positions = JSON.parse(saved);
        if (!Array.isArray(positions) || !positions.length) return;

        // Clear existing rows (except header)
        const list = $('positions-list');
        const rows = list.querySelectorAll('.pos-row');
        rows.forEach(r => r.remove());

        // Rebuild rows from saved data
        positions.forEach(p => {
            const row = document.createElement('div');
            row.className = 'pos-row';
            row.innerHTML = `
                <input type="text" class="ticker-input" value="${p.symbol}" spellcheck="false">
                <input type="number" class="value-input" value="${p.market_value}">
                <button class="pos-remove" aria-label="Remove">−</button>
            `;
            list.appendChild(row);
            row.querySelector('.pos-remove').addEventListener('click', () => row.remove());
        });
    } catch (e) { /* noop */ }
}

// Load saved portfolio on page load
loadSavedPortfolio();

// ── Tab switching ──
document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        const panel = $(`panel-${btn.dataset.tab}`);
        if (panel) panel.classList.add('active');
    });
});

// ── Manual Entry ──
$('add-position-btn').addEventListener('click', () => {
    const list = $('positions-list');
    const row = document.createElement('div');
    row.className = 'pos-row';
    row.innerHTML = `
        <input type="text" class="ticker-input" placeholder="TSLA" spellcheck="false">
        <input type="number" class="value-input" placeholder="5000">
        <button class="pos-remove" aria-label="Remove">−</button>
    `;
    list.appendChild(row);
    row.querySelector('.ticker-input').focus();
    row.querySelector('.pos-remove').addEventListener('click', () => row.remove());
});

// Wire initial remove buttons
document.querySelectorAll('.pos-remove').forEach(btn => {
    btn.addEventListener('click', () => btn.closest('.pos-row').remove());
});

$('analyze-btn').addEventListener('click', () => {
    const positions = collectPositions();
    if (!positions.length) return showError('Add at least one ticker with a dollar value.');
    savePortfolio(positions);
    analyzePortfolio(positions);
});

function collectPositions() {
    const positions = [];
    document.querySelectorAll('.pos-row').forEach(row => {
        const ticker = row.querySelector('.ticker-input').value.trim().toUpperCase();
        const value = parseFloat(row.querySelector('.value-input').value);
        if (ticker && value > 0) positions.push({ symbol: ticker, market_value: value });
    });
    return positions;
}

// ── CSV Upload ──
const dropzone = $('dropzone');
const csvInput = $('csv-file-input');

dropzone.addEventListener('click', () => csvInput.click());
dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('drag-over'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));
dropzone.addEventListener('drop', e => {
    e.preventDefault();
    dropzone.classList.remove('drag-over');
    if (e.dataTransfer.files.length) handleCSV(e.dataTransfer.files[0]);
});
csvInput.addEventListener('change', e => { if (e.target.files.length) handleCSV(e.target.files[0]); });

async function handleCSV(file) {
    if (!file.name.endsWith('.csv')) return showError('Must be a .csv file.');
    const fd = new FormData();
    fd.append('file', file);
    try {
        dropzone.querySelector('.drop-label').textContent = `Parsing ${file.name}…`;
        const r = await fetch(`${API_BASE}/api/upload-csv`, { method: 'POST', body: fd });
        if (!r.ok) { const e = await r.json(); throw new Error(e.detail || 'Parse failed'); }
        const data = await r.json();
        csvPositions = data.positions;

        const preview = $('csv-preview');
        preview.classList.remove('hidden');
        preview.textContent = `${csvPositions.length} positions found:\n` +
            csvPositions.map(p => `  ${p.symbol}  $${p.market_value.toLocaleString()}`).join('\n');

        dropzone.querySelector('.drop-label').textContent = `✓ ${file.name}`;
        $('analyze-csv-btn').classList.remove('hidden');
    } catch (err) {
        showError(`CSV error: ${err.message}`);
        dropzone.querySelector('.drop-label').textContent = 'Drop your CSV here or click to browse';
    }
}

$('analyze-csv-btn').addEventListener('click', () => {
    if (csvPositions && csvPositions.length) {
        savePortfolio(csvPositions);
        analyzePortfolio(csvPositions);
    }
});

// ── Questrade ──
$('questrade-connect-btn').addEventListener('click', () => {
    window.location.href = `${API_BASE}/auth/questrade`;
});

// ── Definitions Toggle ──
$('defs-toggle').addEventListener('click', () => {
    const btn = $('defs-toggle');
    const grid = $('defs-grid');
    btn.classList.toggle('open');
    grid.classList.toggle('open');
});

// ── Analyze ──
async function analyzePortfolio(positions) {
    showSection('loading');
    animateLoading();
    try {
        const r = await fetch(`${API_BASE}/api/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ positions }),
        });
        if (!r.ok) {
            const e = await r.json();
            throw new Error(e.detail || 'Analysis failed');
        }
        renderResults(await r.json());
    } catch (err) {
        showSection('input');
        showError(err.message);
    }
}

// ── Render Results ──
function renderResults(data) {
    showSection('results');
    const d = data.decomposition;

    // Count-up animation for stat cards
    countUp('market-pct', d.market_pct, '%');
    countUp('smb-pct', d.smb_pct, '%');
    countUp('hml-pct', d.hml_pct, '%');
    countUp('idio-pct', d.idiosyncratic_pct, '%');
    countUp('vol-value', d.total_annual_vol, '%');

    // Proportion bar animation
    setTimeout(() => {
        $('bar-mkt').style.flexBasis = `${d.market_pct}%`;
        $('bar-smb').style.flexBasis = `${d.smb_pct}%`;
        $('bar-hml').style.flexBasis = `${d.hml_pct}%`;
        $('bar-idio').style.flexBasis = `${d.idiosyncratic_pct}%`;
    }, 100);

    // Flamegraph
    if (flamegraph) flamegraph.destroy();
    flamegraph = new RiskFlamegraph('flamegraph');

    const fg = data.flamegraph;
    fg.annualVol = `${d.total_annual_vol}% Annual Vol`;
    // Propagate factor type to children for coloring
    if (fg.children) {
        fg.children.forEach(ch => {
            if (ch.children) {
                ch.children.forEach(s => { s.factor = ch.factor; });
            }
        });
    }
    flamegraph.render(fg);

    // Insight — typewriter effect
    typewriter('insight-text', data.insight);

    // Detail table with low-R² warnings
    fillDetailTable(data.stock_details);

    // Show insufficient-data warnings
    showDataWarnings(data.stock_details);

    // Show realized vol comparison if available
    showRealizedVol(d);
}

function fillDetailTable(details) {
    const tbody = $('detail-tbody');
    tbody.innerHTML = '';

    for (const [ticker, d] of Object.entries(details)) {
        const row = document.createElement('tr');
        const r2Low = d.r_squared < 0.3;
        const insufficientData = d.sufficient_data === false;
        row.innerHTML = `
            <td>${ticker}${insufficientData ? ' <span style="color:var(--clr-hml)" title="Insufficient data (<60 days)">⚠</span>' : ''}</td>
            <td class="${d.beta_mkt >= 0 ? 'num-pos' : 'num-neg'}">${d.beta_mkt.toFixed(3)}</td>
            <td class="${d.beta_smb >= 0 ? 'num-pos' : 'num-neg'}">${d.beta_smb.toFixed(3)}</td>
            <td class="${d.beta_hml >= 0 ? 'num-pos' : 'num-neg'}">${d.beta_hml.toFixed(3)}</td>
            <td>${(d.alpha * 10000).toFixed(2)} bps</td>
            <td class="${r2Low ? 'warn-r2' : ''}">${d.r_squared.toFixed(3)}</td>
            <td>${d.n_observations}${insufficientData ? ' ⚠' : ''}</td>
        `;
        tbody.appendChild(row);
    }
}

function showDataWarnings(details) {
    // Remove any previous warning
    const prev = document.getElementById('data-warning');
    if (prev) prev.remove();

    const warnings = [];
    for (const [ticker, d] of Object.entries(details)) {
        if (d.sufficient_data === false) {
            warnings.push(`${ticker} has only ${d.n_observations} trading days of history (minimum 60 needed for stable betas)`);
        } else if (d.r_squared < 0.2) {
            warnings.push(`${ticker} has very low R² (${d.r_squared.toFixed(3)}) — the factor model explains little of its movement`);
        }
    }

    if (warnings.length) {
        const warning = document.createElement('div');
        warning.id = 'data-warning';
        warning.className = 'err';
        warning.style.background = 'rgba(251,191,36,0.06)';
        warning.style.borderColor = 'rgba(251,191,36,0.2)';
        warning.style.color = 'var(--clr-hml)';
        warning.innerHTML = `
            <div>
                <strong>⚠ Data Quality Notes</strong><br>
                ${warnings.map(w => `<span style="font-size:0.78rem;color:var(--text-secondary)">${w}</span>`).join('<br>')}
            </div>
            <button class="err-x" onclick="this.closest('.err').remove()">×</button>
        `;
        // Insert before the detail table
        const detailSection = $('detail-section');
        detailSection.parentNode.insertBefore(warning, detailSection);
    }
}

function showRealizedVol(decomposition) {
    // Remove previous
    const prev = document.getElementById('realized-vol-note');
    if (prev) prev.remove();

    if (decomposition.realized_vol != null) {
        const modelVol = decomposition.total_annual_vol;
        const realizedVol = decomposition.realized_vol;
        const diff = Math.abs(modelVol - realizedVol);
        const note = document.createElement('div');
        note.id = 'realized-vol-note';
        note.style.cssText = 'font-size:0.72rem;color:var(--text-muted);text-align:center;margin-top:-1rem;margin-bottom:1rem;font-family:var(--mono)';
        note.textContent = `Model-implied vol: ${modelVol.toFixed(1)}%  |  Historical realized vol: ${realizedVol.toFixed(1)}%  |  Δ ${diff.toFixed(1)}%`;
        // Insert after the stat cards section
        const statCards = document.querySelector('.stat-cards');
        if (statCards) statCards.parentNode.insertBefore(note, statCards.nextSibling);
    }
}

// ── UI Helpers ──
function showSection(name) {
    Object.values(sections).forEach(s => s.classList.add('hidden'));
    if (sections[name]) sections[name].classList.remove('hidden');
    hideError();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function showError(msg) {
    $('error-text').textContent = msg;
    $('error-banner').classList.remove('hidden');
}
function hideError() {
    $('error-banner').classList.add('hidden');
}
$('error-dismiss').addEventListener('click', hideError);

$('back-btn').addEventListener('click', () => {
    showSection('input');
    // Reset bars
    ['bar-mkt', 'bar-smb', 'bar-hml', 'bar-idio'].forEach(id => {
        $(id).style.flexBasis = '0';
    });
});

function countUp(id, target, suffix) {
    const el = $(id);
    const dur = 1000;
    const start = performance.now();

    function step(now) {
        const t = Math.min((now - start) / dur, 1);
        const ease = 1 - Math.pow(1 - t, 3); // easeOutCubic
        el.textContent = (target * ease).toFixed(1) + suffix;
        if (t < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
}

function typewriter(id, text) {
    const el = $(id);
    el.textContent = '';
    let i = 0;
    function tick() {
        if (i < text.length) {
            el.textContent += text[i++];
            setTimeout(tick, 12);
        }
    }
    setTimeout(tick, 500);
}

function animateLoading() {
    const msgs = [
        'Downloading Fama-French factors from Ken French\'s library…',
        'Fetching 18 months of daily prices from Stooq…',
        'Running 252-day rolling OLS regressions for each stock…',
        'Computing Σ = B·F·Bᵀ + D variance decomposition…',
        'Almost there — generating your risk profile…',
    ];
    let idx = 0;
    const el = $('loading-text');
    el.textContent = msgs[0];

    const iv = setInterval(() => {
        idx++;
        if (idx < msgs.length) el.textContent = msgs[idx];
        else clearInterval(iv);
    }, 3500);
}
