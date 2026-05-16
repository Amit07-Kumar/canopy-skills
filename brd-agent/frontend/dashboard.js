const LIVE_DASHBOARD_TABS = new Set(['overview', 'conflicts']);

let dashboardTabsBound = false;

function getDashboardDataset() {
    const live = window.REQUIREWISE_DASHBOARD_DATA;
    return live && typeof live === 'object' ? live : {};
}

function initDashboard(projectName) {
    const subtitle = document.getElementById('dash-project-name');
    const data = getDashboardDataset();
    if (subtitle) {
        subtitle.textContent = projectName || data.project_name || 'Live project view';
    }

    markUnavailableViews();
    renderUnavailablePanes();
    setupTabs();
    renderOverview();
    renderConflicts(document.querySelector('.conflict-filter.active-filter')?.dataset.filter || 'all');
    bindNLEditor();
}

function markUnavailableViews() {
    document.querySelectorAll('.dash-tab').forEach((button) => {
        const tab = button.dataset.tab;
        if (LIVE_DASHBOARD_TABS.has(tab)) {
            button.classList.remove('opacity-50', 'cursor-not-allowed');
            button.removeAttribute('title');
            return;
        }

        button.classList.add('opacity-50', 'cursor-not-allowed');
        button.title = 'Disabled in live mode until a real backend workflow is wired.';
    });
}

function setupTabs() {
    if (!dashboardTabsBound) {
        document.querySelectorAll('.dash-tab').forEach((button) => {
            button.addEventListener('click', () => {
                const target = button.dataset.tab;
                if (!LIVE_DASHBOARD_TABS.has(target)) {
                    window.showAppToast?.('This dashboard view is disabled until a live backend service is connected.', true);
                    return;
                }

                activateDashboardTab(target);
            });
        });

        document.querySelectorAll('.conflict-filter').forEach((button) => {
            button.addEventListener('click', () => {
                document.querySelectorAll('.conflict-filter').forEach((item) => item.classList.remove('active-filter'));
                button.classList.add('active-filter');
                renderConflicts(button.dataset.filter || 'all');
            });
        });

        dashboardTabsBound = true;
    }

    const activeTab = document.querySelector('.dash-tab.active-tab')?.dataset.tab;
    activateDashboardTab(LIVE_DASHBOARD_TABS.has(activeTab) ? activeTab : 'overview');
}

function activateDashboardTab(target) {
    document.querySelectorAll('.dash-tab').forEach((button) => {
        button.classList.toggle('active-tab', button.dataset.tab === target);
    });

    document.querySelectorAll('.tab-pane').forEach((pane) => pane.classList.add('hidden'));
    document.getElementById(`tab-${target}`)?.classList.remove('hidden');
}

function renderOverview() {
    renderKPIBar();
    renderDataSources();
    renderActivityFeed();
    renderStakeholderSentiment();
}

function renderKPIBar() {
    const data = getDashboardDataset();
    const metrics = data.metrics || {};
    const cards = [
        {
            label: 'Execution Health',
            value: `${safeNumber(metrics.execution_health)}%`,
            icon: 'Execution',
            accent: 'text-blue-400',
            panel: 'bg-blue-500/10 border-blue-500/20'
        },
        {
            label: 'Context Completeness',
            value: `${safeNumber(metrics.context_completeness)}%`,
            icon: 'Context',
            accent: 'text-emerald-400',
            panel: 'bg-emerald-500/10 border-emerald-500/20'
        },
        {
            label: 'Automation Coverage',
            value: `${safeNumber(metrics.automation_coverage)}%`,
            icon: 'Automation',
            accent: 'text-purple-400',
            panel: 'bg-purple-500/10 border-purple-500/20'
        },
        {
            label: 'BRDs Available',
            value: `${safeNumber(metrics.brd_count ?? data.brd_count)}`,
            icon: 'BRDs',
            accent: 'text-cyan-400',
            panel: 'bg-cyan-500/10 border-cyan-500/20'
        }
    ];

    const container = document.getElementById('kpi-bar');
    if (!container) {
        return;
    }

    container.innerHTML = cards.map((card) => `
        <div class="glass-card p-5 rounded-2xl flex items-center gap-4 border ${card.panel}">
            <div class="min-w-0">
                <p class="text-xs text-gray-400 mb-0.5 uppercase tracking-wider">${escapeHtml(card.label)}</p>
                <p class="text-3xl font-bold ${card.accent}">${escapeHtml(card.value)}</p>
                <p class="text-xs text-gray-500 mt-1">${escapeHtml(card.icon)}</p>
            </div>
        </div>
    `).join('');
}

function renderDataSources() {
    const data = getDashboardDataset();
    const sources = Array.isArray(data.data_sources) && data.data_sources.length > 0
        ? data.data_sources
        : buildDerivedSources(data);
    const container = document.getElementById('data-sources-bar');
    if (!container) {
        return;
    }

    container.innerHTML = sources.map((source) => {
        const status = normaliseStatus(source.status);
        return `
            <div class="flex items-center gap-3 p-3 rounded-xl bg-white/5 border border-white/5">
                <div class="w-10 h-10 rounded-xl bg-black/20 border border-white/5 flex items-center justify-center text-xs font-semibold text-gray-200">
                    ${escapeHtml(source.shortLabel || source.label || 'Data')}
                </div>
                <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-white">${escapeHtml(String(source.count ?? 0))} <span class="text-xs text-gray-400 font-normal">${escapeHtml(source.label || 'Records')}</span></p>
                    <div class="flex items-center gap-1 mt-0.5">
                        <div class="w-1.5 h-1.5 rounded-full ${status.dot}"></div>
                        <span class="text-xs ${status.text}">${escapeHtml(status.label)}</span>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function renderActivityFeed() {
    const container = document.getElementById('activity-feed');
    if (!container) {
        return;
    }

    const activity = Array.isArray(getDashboardDataset().recent_activity)
        ? getDashboardDataset().recent_activity
        : [];

    if (activity.length === 0) {
        container.innerHTML = emptyState('No live activity yet', 'Recent activity appears here after meetings, BRD updates, or integrations create real records.');
        return;
    }

    container.innerHTML = activity.map((item) => `
        <li class="flex items-start gap-3">
            <div class="w-8 h-8 rounded-full bg-white/5 border border-white/10 flex items-center justify-center flex-shrink-0 text-xs font-semibold text-gray-200">
                ${escapeHtml(item.icon || 'LOG')}
            </div>
            <div class="flex-1 min-w-0">
                <p class="text-sm text-white leading-snug">${escapeHtml(item.text || item.message || 'Activity recorded')}</p>
                <p class="text-xs text-gray-500 mt-0.5">${escapeHtml(item.time || item.timestamp || '')}</p>
            </div>
        </li>
    `).join('');
}

function renderStakeholderSentiment() {
    const container = document.getElementById('stakeholder-sentiment-list');
    if (!container) {
        return;
    }

    const signals = Array.isArray(getDashboardDataset().business_signals)
        ? getDashboardDataset().business_signals
        : [];

    if (signals.length === 0) {
        container.innerHTML = emptyState('No live stakeholder signals', 'This card stays empty until real meeting analysis produces stakeholder sentiment.');
        return;
    }

    container.innerHTML = signals.map((signal) => {
        const sentiment = safeNumber(signal.sentiment);
        const color = signal.color || '#60a5fa';
        return `
            <div>
                <div class="flex items-center justify-between mb-1">
                    <div class="flex items-center gap-2">
                        <div class="w-2.5 h-2.5 rounded-full" style="background:${escapeHtml(color)}"></div>
                        <span class="text-sm text-gray-300">${escapeHtml(signal.name || 'Stakeholder')}</span>
                        <span class="text-xs text-gray-500">${escapeHtml(signal.role || '')}</span>
                    </div>
                    <span class="text-xs font-medium text-gray-300">${escapeHtml(String(sentiment))}%</span>
                </div>
                <div class="sentiment-bar">
                    <div class="sentiment-fill" style="width:${sentiment}%;background:${escapeHtml(color)}"></div>
                </div>
            </div>
        `;
    }).join('');
}

function renderConflicts(filter = 'all') {
    const container = document.getElementById('conflicts-full-list');
    if (!container) {
        return;
    }

    const allConflicts = Array.isArray(getDashboardDataset().conflicts)
        ? getDashboardDataset().conflicts
        : [];
    const filteredConflicts = filter === 'all'
        ? allConflicts
        : allConflicts.filter((conflict) => String(conflict.severity || '').toLowerCase() === filter);

    if (filteredConflicts.length === 0) {
        container.innerHTML = emptyState('No live conflicts found', filter === 'all'
            ? 'Requirement conflicts will appear here when they are detected from real project data.'
            : `No live ${filter} conflicts found.`);
        return;
    }

    container.innerHTML = filteredConflicts.map((conflict) => buildConflictCard(conflict)).join('');
    container.querySelectorAll('.conflict-card-header').forEach((header) => {
        header.addEventListener('click', () => {
            const card = header.closest('.conflict-card');
            const body = card?.querySelector('.conflict-card-body');
            body?.classList.toggle('hidden');
        });
    });
}

function buildConflictCard(conflict) {
    const severity = String(conflict.severity || 'Low');
    const severityClass = {
        Critical: 'badge-critical',
        High: 'badge-high',
        Medium: 'badge-medium',
        Low: 'badge-low'
    }[severity] || 'badge-low';

    const status = String(conflict.status || 'Open');
    const statusClass = status === 'Resolved'
        ? 'text-green-400 bg-green-500/10 border-green-500/20'
        : status === 'In Review'
            ? 'text-yellow-400 bg-yellow-500/10 border-yellow-500/20'
            : 'text-red-400 bg-red-500/10 border-red-500/20';

    const sources = Array.isArray(conflict.sources) ? conflict.sources : [];
    const suggestions = Array.isArray(conflict.suggestions)
        ? conflict.suggestions
        : conflict.suggestion
            ? [conflict.suggestion]
            : [];

    const sourcesHtml = sources.length > 0
        ? sources.map((source) => `
            <div class="p-3 rounded-lg bg-black/30 border border-white/5">
                <div class="flex items-center gap-2 mb-1 flex-wrap">
                    <span class="text-xs font-medium text-blue-400">${escapeHtml(source.type || 'Source')}</span>
                    <span class="text-xs text-gray-500">${escapeHtml(source.from || source.author || '')}</span>
                    <span class="text-xs text-gray-500">${escapeHtml(source.date || '')}</span>
                </div>
                <p class="text-xs text-gray-300 italic">${escapeHtml(source.excerpt || source.quote || 'No source excerpt provided.')}</p>
            </div>
        `).join('')
        : '<p class="text-xs text-gray-500">No source excerpts were returned by the live API.</p>';

    const suggestionsHtml = suggestions.length > 0
        ? suggestions.map((suggestion) => `
            <div class="flex items-start gap-2">
                <div class="w-4 h-4 rounded-full bg-accent/20 border border-accent/30 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <div class="w-1.5 h-1.5 rounded-full bg-accent"></div>
                </div>
                <p class="text-xs text-gray-300">${escapeHtml(suggestion)}</p>
            </div>
        `).join('')
        : '<p class="text-xs text-gray-500">No resolution suggestions were returned by the live API.</p>';

    return `
        <div class="conflict-card glass-card rounded-2xl overflow-hidden">
            <div class="conflict-card-header p-5 cursor-pointer hover:bg-white/5 transition-all">
                <div class="flex items-start justify-between gap-4">
                    <div class="flex-1 min-w-0">
                        <div class="flex flex-wrap items-center gap-2 mb-2">
                            <span class="px-2.5 py-0.5 rounded-full text-xs font-semibold ${severityClass}">${escapeHtml(severity)}</span>
                            <span class="px-2.5 py-0.5 rounded-full text-xs border ${statusClass} font-medium">${escapeHtml(status)}</span>
                            <span class="text-xs text-gray-500 font-mono">${escapeHtml(conflict.type || 'conflict')}</span>
                        </div>
                        <h4 class="text-base font-semibold text-white mb-1">${escapeHtml(conflict.title || 'Untitled conflict')}</h4>
                        <p class="text-sm text-gray-400 leading-relaxed">${escapeHtml(conflict.description || 'No conflict description was returned.')}</p>
                    </div>
                    <div class="flex-shrink-0 text-xs text-gray-500">${escapeHtml(conflict.createdAt || conflict.date || '')}</div>
                </div>
            </div>
            <div class="conflict-card-body hidden border-t border-white/5">
                <div class="p-5 grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <h5 class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Conflicting Sources</h5>
                        <div class="space-y-3">${sourcesHtml}</div>
                    </div>
                    <div>
                        <h5 class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Resolution Guidance</h5>
                        <div class="space-y-2">${suggestionsHtml}</div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderUnavailablePanes() {
    const messages = {
        graph: {
            title: 'Knowledge graph unavailable in live mode',
            detail: 'This tab previously depended on demo graph data. It stays disabled until /api/knowledge-graph is backed by a real workflow.'
        },
        brd: {
            title: 'BRD editor unavailable in live mode',
            detail: 'Natural-language BRD editing is hidden until a real update API is wired end-to-end.'
        },
        stakeholders: {
            title: 'Stakeholder views unavailable in live mode',
            detail: 'These persona-specific panels were using demo projections. They remain disabled until live stakeholder analytics are connected.'
        },
        traceability: {
            title: 'Traceability matrix unavailable in live mode',
            detail: 'This view will return when requirements, sources, and test cases are coming from live project records.'
        }
    };

    Object.entries(messages).forEach(([tab, message]) => {
        const pane = document.getElementById(`tab-${tab}`);
        if (!pane) {
            return;
        }

        pane.innerHTML = `
            <div class="glass-card p-8 rounded-2xl text-center max-w-3xl mx-auto">
                <p class="text-sm uppercase tracking-[0.2em] text-gray-500 mb-3">Live Mode</p>
                <h3 class="text-2xl font-semibold text-white mb-3">${escapeHtml(message.title)}</h3>
                <p class="text-sm text-gray-400 leading-relaxed">${escapeHtml(message.detail)}</p>
            </div>
        `;
    });
}

function bindNLEditor() {
    const button = document.getElementById('btn-nl-update-brd');
    const result = document.getElementById('nl-edit-result');
    if (!button || button.dataset.liveBound === 'true') {
        return;
    }

    button.dataset.liveBound = 'true';
    button.addEventListener('click', () => {
        if (result) {
            result.classList.remove('hidden', 'bg-green-500/10', 'border-green-500/30', 'text-green-300');
            result.classList.add('bg-red-500/10', 'border-red-500/30', 'text-red-300');
            result.textContent = 'Live BRD editing is disabled until a real BRD update workflow is connected.';
        }
        window.showAppToast?.('Live BRD editing is not wired yet.', true);
    });
}

function buildDerivedSources(data) {
    const metrics = data.metrics || {};
    const activityCount = Array.isArray(data.recent_activity) ? data.recent_activity.length : 0;
    const conflictCount = Array.isArray(data.conflicts) ? data.conflicts.length : 0;
    const brdCount = safeNumber(metrics.brd_count ?? data.brd_count);

    return [
        {
            label: 'Activity records',
            shortLabel: 'ACT',
            count: activityCount,
            status: activityCount > 0 ? 'live' : 'pending'
        },
        {
            label: 'Conflict records',
            shortLabel: 'CFL',
            count: conflictCount,
            status: conflictCount > 0 ? 'live' : 'pending'
        },
        {
            label: 'Stakeholder signals',
            shortLabel: 'SIG',
            count: Array.isArray(data.business_signals) ? data.business_signals.length : 0,
            status: Array.isArray(data.business_signals) && data.business_signals.length > 0 ? 'live' : 'pending'
        },
        {
            label: 'BRDs available',
            shortLabel: 'BRD',
            count: brdCount,
            status: brdCount > 0 ? 'live' : 'pending'
        }
    ];
}

function normaliseStatus(value) {
    const status = String(value || 'pending').toLowerCase();
    if (status === 'live' || status === 'ok' || status === 'connected') {
        return { label: 'Live', dot: 'bg-green-400', text: 'text-green-400' };
    }
    if (status === 'unavailable' || status === 'error' || status === 'failed') {
        return { label: 'Unavailable', dot: 'bg-red-400', text: 'text-red-400' };
    }
    return { label: 'Pending', dot: 'bg-yellow-400', text: 'text-yellow-400' };
}

function safeNumber(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? Math.round(parsed) : 0;
}

function emptyState(title, detail) {
    return `
        <div class="glass-card p-8 rounded-2xl text-center text-gray-400">
            <p class="text-sm font-semibold text-white mb-2">${escapeHtml(title)}</p>
            <p class="text-xs leading-relaxed max-w-md mx-auto">${escapeHtml(detail)}</p>
        </div>
    `;
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
