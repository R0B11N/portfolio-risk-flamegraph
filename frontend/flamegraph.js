/**
 * 3D flamegraph component using CSS DOM elements.
 * Bottom-up hierarchy: portfolio → factors → stocks.
 */

const FACTOR_CLASSES = {
    market: 'factor-market',
    smb: 'factor-smb',
    hml: 'factor-hml',
    idiosyncratic: 'factor-idio',
};

class RiskFlamegraph {
    constructor(containerId) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        this.currentRoot = null;
        this.rootData = null;
        this.tooltip = null;

        this._createTooltip();
        this._onResize = this._onResize.bind(this);
        window.addEventListener('resize', this._onResize);
    }

    render(data) {
        this.rootData = data;
        this.currentRoot = data;
        this._rebuild();
    }

    _rebuild() {
        this.container.innerHTML = '';
        const rows = this._flatten(this.currentRoot);

        // Render bottom-up: root at bottom, children above
        for (let li = rows.length - 1; li >= 0; li--) {
            const row = rows[li];
            const rowEl = document.createElement('div');
            rowEl.className = 'fg-row';

            row.forEach(node => {
                const pct = (node.value / this.currentRoot.value) * 100;
                const bar = document.createElement('div');

                // Factor class
                const isRoot = (li === 0 && !node.factor);
                const factorClass = isRoot ? 'factor-root' : (FACTOR_CLASSES[node.factor] || 'factor-root');
                bar.className = `fg-bar ${factorClass}`;

                // High idiosyncratic glow
                if (node.factor === 'idiosyncratic' && node.value > 15) {
                    bar.classList.add('high-idio');
                }
                if (node.meta && node.meta.r_squared !== undefined && node.meta.r_squared < 0.3) {
                    bar.classList.add('high-idio'); // Low R² also gets glow
                }

                // Width
                bar.style.flex = `0 0 ${pct}%`;
                bar.style.maxWidth = `${pct}%`;

                // Labels
                if (pct > 5) {
                    const nameEl = document.createElement('div');
                    nameEl.className = 'fg-bar-name';
                    nameEl.textContent = this._formatName(node, isRoot);
                    bar.appendChild(nameEl);
                }
                if (pct > 4) {
                    const pctEl = document.createElement('div');
                    pctEl.className = 'fg-bar-pct';
                    pctEl.textContent = `${node.value.toFixed(1)}%`;
                    bar.appendChild(pctEl);
                }

                // Tooltip
                bar.addEventListener('mouseenter', (ev) => this._showTip(ev, node));
                bar.addEventListener('mousemove', (ev) => this._moveTip(ev));
                bar.addEventListener('mouseleave', () => this._hideTip());

                // Click to drill
                const hasChildren = node.children && node.children.length;
                const canZoomOut = li === 0 && this.currentRoot !== this.rootData;
                bar.style.cursor = (hasChildren || canZoomOut) ? 'pointer' : 'default';

                bar.addEventListener('click', () => {
                    if (canZoomOut) {
                        this.currentRoot = this.rootData;
                        this._rebuild();
                    } else if (hasChildren) {
                        this.currentRoot = node;
                        this._rebuild();
                    }
                });

                rowEl.appendChild(bar);
            });

            this.container.appendChild(rowEl);
        }

        // Entrance animation
        const bars = this.container.querySelectorAll('.fg-bar');
        bars.forEach((b, i) => {
            b.style.opacity = '0';
            b.style.transform = 'translateY(8px)';
            setTimeout(() => {
                b.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
                b.style.opacity = '1';
                b.style.transform = 'translateY(0)';
            }, 40 * i);
        });
    }

    _flatten(node) {
        const rows = [[node]];
        if (node.children && node.children.length) {
            rows.push(node.children);
            const gc = [];
            node.children.forEach(c => {
                if (c.children && c.children.length) gc.push(...c.children);
            });
            if (gc.length) rows.push(gc);
        }
        return rows;
    }

    _formatName(node, isRoot) {
        if (isRoot) {
            return `Your Portfolio — ${node.annualVol || ''}`;
        }
        return node.name;
    }

    // Tooltip
    _createTooltip() {
        this.tooltip = document.createElement('div');
        this.tooltip.className = 'fg-tooltip';
        document.body.appendChild(this.tooltip);
    }

    _showTip(ev, node) {
        let h = `<div class="tt-name">${node.name}</div>`;
        h += `<div class="tt-value">${node.value.toFixed(1)}% of total portfolio variance</div>`;

        if (node.meta) {
            const m = node.meta;
            const lines = [];
            if (m.beta_mkt != null) lines.push(`β Market: ${m.beta_mkt.toFixed(3)}`);
            if (m.beta_smb != null) lines.push(`β Size: ${m.beta_smb.toFixed(3)}`);
            if (m.beta_hml != null) lines.push(`β Value: ${m.beta_hml.toFixed(3)}`);
            if (m.r_squared != null) {
                const r2 = m.r_squared.toFixed(3);
                lines.push(`R²: ${r2}${m.r_squared < 0.3 ? ' ⚠ low' : ''}`);
            }
            if (m.weight != null) lines.push(`Weight: ${(m.weight * 100).toFixed(1)}%`);
            h += `<div class="tt-detail">${lines.join('<br>')}</div>`;
        }

        this.tooltip.innerHTML = h;
        this.tooltip.style.opacity = '1';
        this._moveTip(ev);
    }

    _moveTip(ev) {
        const pad = 14;
        let x = ev.clientX + pad;
        let y = ev.clientY - pad;
        // Keep on screen
        const rect = this.tooltip.getBoundingClientRect();
        if (x + rect.width > window.innerWidth - 10) x = ev.clientX - rect.width - pad;
        if (y < 10) y = 10;
        this.tooltip.style.left = x + 'px';
        this.tooltip.style.top = y + 'px';
    }

    _hideTip() { this.tooltip.style.opacity = '0'; }

    _onResize() {
        clearTimeout(this._rt);
        this._rt = setTimeout(() => { if (this.currentRoot) this._rebuild(); }, 200);
    }

    destroy() {
        window.removeEventListener('resize', this._onResize);
        if (this.tooltip) this.tooltip.remove();
    }
}

window.RiskFlamegraph = RiskFlamegraph;
