// RequireWise BRD Agent - Frontend Logic

const API_BASE = '/api';

const PORTAL_MODULES = {
    meetings: { directPort: '5098', directPath: '/', gatewayPath: '/' },
    brd: { directPort: '8025', directPath: '/', gatewayPath: '/brd/' }
};

const CANOPY_GATEWAY_PORT = '5080';

function buildPortalModuleUrl(moduleKey) {
    const module = PORTAL_MODULES[moduleKey];
    if (!module) {
        return '#';
    }

    const { protocol, hostname, port, pathname } = window.location;
    const currentPort = port || (protocol === 'https:' ? '443' : '80');
    const isGateway = currentPort === CANOPY_GATEWAY_PORT || pathname.startsWith('/brd');

    if (isGateway) {
        return `${window.location.origin}${module.gatewayPath}`;
    }

    if (currentPort === module.directPort) {
        return module.directPath;
    }

    return `${protocol}//${hostname}:${module.directPort}${module.directPath}`;
}

function initPortalShell() {
    const meetingsLink = document.getElementById('portal-link-meetings');
    const brdLink = document.getElementById('portal-link-brd');

    if (meetingsLink) {
        meetingsLink.href = buildPortalModuleUrl('meetings');
    }
    if (brdLink) {
        brdLink.href = buildPortalModuleUrl('brd');
    }
}

// ─── Filename Helpers ──────────────────────────────────────────
// toSlug: Convert any string to lowercase-hyphen slug for API filenames
// "My Cool Project!" → "my-cool-project"
function toSlug(str) {
    return str
        .toLowerCase()
        .replace(/[^a-z0-9\s-]/g, '')  // remove special characters
        .replace(/\s+/g, '-')           // spaces → hyphens
        .replace(/-+/g, '-')            // collapse multiple hyphens
        .replace(/^-|-$/g, '');          // trim leading/trailing hyphens
}

// toTitleCase: Convert slug back to display name with each word capitalized
// "aidhunik-payment-system" → "Aidhunik Payment System"
function toSentenceCase(slug) {
    return slug
        .replace(/-/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase());
}

// DOM Elements
const projectSelect = document.getElementById('project-select');
const btnUpdateBrd = document.getElementById('btn-update-brd');
const brdStatus = document.getElementById('brd-status');
const brdStatusText = document.getElementById('brd-status-text');
const updateBrdSummary = document.getElementById('update-brd-summary');

const transcriptInput = document.getElementById('transcript-input');
const btnSummarizeTranscript = document.getElementById('btn-summarize-transcript');
const transcriptResult = document.getElementById('transcript-result');
const btnBrdFromTranscript = document.getElementById('btn-brd-from-transcript');

const btnRecord = document.getElementById('btn-record');
const recordIcon = document.getElementById('record-icon');
const recordPulse = document.getElementById('record-pulse');
const recordStatus = document.getElementById('record-status');
const audioResult = document.getElementById('audio-result');
const btnBrdFromAudio = document.getElementById('btn-brd-from-audio');

const taskSummaryInput = document.getElementById('task-summary-input');
const btnAssignTasks = document.getElementById('btn-assign-tasks');
const tasksResult = document.getElementById('tasks-result');

const toast = document.getElementById('toast');
const toastMsg = document.getElementById('toast-msg');

// BRD Generator Elements
const brdGeneratorText = document.getElementById('brd-generator-text');
const brdGeneratorFilename = document.getElementById('brd-generator-filename');
const brdGeneratorSlugPreview = document.getElementById('brd-generator-slug-preview');
const brdGeneratorSlugText = document.getElementById('brd-generator-slug-text');
const btnGenerateBrd = document.getElementById('btn-generate-brd');
const brdGeneratorStatus = document.getElementById('brd-generator-status');
const brdGeneratorStatusText = document.getElementById('brd-generator-status-text');
const brdGeneratorProgress = document.getElementById('brd-generator-progress');

// BRD Document Viewer Elements (shared panel for generate/update/load)
const brdContentViewer = document.getElementById('brd-content-viewer');
const brdViewerLabel = document.getElementById('brd-viewer-label');
const brdViewerCard = document.getElementById('brd-viewer-card');

// OpenProject Elements
const btnFetchTickets = document.getElementById('btn-fetch-tickets');
const ticketsResult = document.getElementById('tickets-result');
const ticketCountBadge = document.getElementById('ticket-count-badge');

// Phase 2 Elements
const btnToggleDashboard = document.getElementById('btn-toggle-dashboard');
const phase1Container = document.getElementById('phase1-container');
const phase2Container = document.getElementById('phase2-container');
const btnSyncSlack = document.getElementById('btn-sync-slack');
const btnSyncGmail = document.getElementById('btn-sync-gmail');

// Phase 3: Playground Elements
const btnTogglePlayground = document.getElementById('btn-toggle-playground');
const playgroundContainer = document.getElementById('playground-container');
const btnSyncFiles = document.getElementById('btn-sync-files');
const btnSettings = document.getElementById('btn-settings');

// State
let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];
let currentTranscriptSummary = '';
let currentAudioSummary = '';
let currentView = 'phase1'; // 'phase1' | 'phase2' | 'playground'
let currentDashboardProject = '';

// Initialize
async function init() {
    initPortalShell();
    // Load BRD list from real API for the dropdown
    await refreshBrdDropdown();
    bindQuickActions();
    updateWorkspaceSnapshot();

    // Listen for project change to update dashboard if open
    projectSelect.addEventListener('change', () => {
        if (currentView === 'phase2') {
            loadDashboardData(projectSelect.value);
        }
    });

    // Live slug preview for BRD Generator filename input (shows final slug with -brd suffix)
    brdGeneratorFilename.addEventListener('input', () => {
        const slug = toSlug(brdGeneratorFilename.value);
        if (slug) {
            const preview = slug.endsWith('-brd') ? slug : `${slug}-brd`;
            brdGeneratorSlugPreview.classList.remove('hidden');
            brdGeneratorSlugText.textContent = preview;
        } else {
            brdGeneratorSlugPreview.classList.add('hidden');
        }
    });
}

/**
 * Fetches the list of BRDs from /api/list-brds and populates the dropdown.
 * Adds "Detect Automatically" as the first option.
 * Converts slugs to sentence case for display.
 */
async function refreshBrdDropdown() {
    try {
        const response = await fetch(`${API_BASE}/list-brds`);
        const data = await response.json();

        projectSelect.innerHTML = '';

        // Always add "Detect Automatically" as first option
        const autoOption = document.createElement('option');
        autoOption.value = '';
        autoOption.textContent = 'Detect Automatically';
        projectSelect.appendChild(autoOption);

        if (data.success && data.brds && data.brds.length > 0) {
            data.brds.forEach(brd => {
                // brd could be a string (filename) or an object with a filename/name property
                const slug = typeof brd === 'string' ? brd : (brd.filename || brd.name || JSON.stringify(brd));
                const option = document.createElement('option');
                option.value = slug;
                option.textContent = toSentenceCase(slug);
                projectSelect.appendChild(option);
            });
        }

        // Load initial dashboard data with first real project or empty
        const firstProject = projectSelect.options.length > 1 ? projectSelect.options[1].value : '';
        loadDashboardData(firstProject || '');
        updateWorkspaceSnapshot();

    } catch (error) {
        console.error('Failed to load BRD list:', error);
        // Fallback: keep "Detect Automatically" only
        projectSelect.innerHTML = '';
        const autoOption = document.createElement('option');
        autoOption.value = '';
        autoOption.textContent = 'Detect Automatically';
        projectSelect.appendChild(autoOption);
        showToast('Could not load BRD list from server', true);
        updateWorkspaceSnapshot();
    }
}

function bindQuickActions() {
    document.getElementById('btn-quick-dashboard')?.addEventListener('click', () => {
        switchView('phase2');
    });
}

function scrollToCard(cardId) {
    document.getElementById(cardId)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function updateWorkspaceSnapshot() {
    const projectCount = Math.max((projectSelect?.options?.length || 1) - 1, 0);
    const brdCount = Array.isArray(cachedBrdLibrary) ? cachedBrdLibrary.length : 0;
    const conflicts = Array.isArray(window.REQUIREWISE_DASHBOARD_DATA?.conflicts)
        ? window.REQUIREWISE_DASHBOARD_DATA.conflicts.length
        : 0;
    const executionHealth = window.REQUIREWISE_DASHBOARD_DATA?.metrics?.execution_health;

    const modeText = currentView === 'phase2' ? 'Live Dashboard' : 'Core Studio';
    const modeCopy = currentView === 'phase2'
        ? `Reviewing live data for ${currentDashboardProject || 'the selected BRD'} and exposing unsupported views honestly.`
        : 'Use the core studio to generate BRDs, process transcripts, and prepare requirement updates before opening the live dashboard.';

    document.getElementById('rw-stat-mode').textContent = modeText;
    document.getElementById('rw-status-copy').textContent = modeCopy;
    document.getElementById('rw-stat-projects').textContent = String(projectCount);
    document.getElementById('rw-stat-brds').textContent = String(brdCount);
    document.getElementById('rw-stat-health').textContent = Number.isFinite(Number(executionHealth)) ? String(Math.round(Number(executionHealth))) : '--';
    document.getElementById('rw-stat-conflicts').textContent = String(conflicts);
}

// ─── View Switching (Phase 1 ↔ Phase 2 ↔ Playground) ──────
// Helper: transition between any two containers smoothly
function switchView(targetView) {
    if (targetView === 'playground' && typeof initPlayground !== 'function') {
        showToast('Playground is disabled in live mode.', true);
        return;
    }

    if (targetView === currentView) {
        // Toggle back to phase1 if clicking same button again
        targetView = 'phase1';
    }

    const containers = {
        phase1: phase1Container,
        phase2: phase2Container,
        playground: playgroundContainer
    };

    // Reset nav button styles
    btnToggleDashboard.textContent = 'Advanced Dashboard';
    btnToggleDashboard.classList.remove('bg-primary', 'text-white', 'border-primary');
    btnToggleDashboard.classList.add('bg-surface', 'border-white/10');

    btnTogglePlayground.innerHTML = '🧪 Playground';
    btnTogglePlayground.classList.remove('bg-accent', 'text-white', 'border-accent');
    btnTogglePlayground.classList.add('bg-surface', 'border-white/10');

    // Highlight active button
    if (targetView === 'phase2') {
        btnToggleDashboard.textContent = 'Back to Core Features';
        btnToggleDashboard.classList.add('bg-primary', 'text-white', 'border-primary');
        btnToggleDashboard.classList.remove('bg-surface', 'border-white/10');
    } else if (targetView === 'playground') {
        btnTogglePlayground.innerHTML = '← Back to Core';
        btnTogglePlayground.classList.add('bg-accent', 'text-white', 'border-accent');
        btnTogglePlayground.classList.remove('bg-surface', 'border-white/10');
    }

    // Hide current container
    const currentContainer = containers[currentView];
    currentContainer.classList.add('opacity-0');

    setTimeout(() => {
        // Hide all containers
        Object.values(containers).forEach(c => {
            c.classList.add('hidden');
            c.classList.remove('absolute');
        });

        // Show target container
        const targetContainer = containers[targetView];
        targetContainer.classList.remove('hidden');
        setTimeout(() => {
            targetContainer.classList.remove('opacity-0');
        }, 50);

        // Initialize views when shown
        if (targetView === 'phase2') {
            if (typeof initDashboard === 'function') {
                initDashboard(projectSelect.value);
            }
            loadDashboardData(projectSelect.value);
        } else if (targetView === 'playground') {
            if (typeof initPlayground === 'function') {
                initPlayground();
            }
        }

        currentView = targetView;
        updateWorkspaceSnapshot();
    }, 300);
}

btnToggleDashboard.addEventListener('click', () => switchView(currentView === 'phase2' ? 'phase1' : 'phase2'));
btnTogglePlayground?.addEventListener('click', () => switchView(currentView === 'playground' ? 'phase1' : 'playground'));

// ─── Settings Modal ──────
btnSettings.addEventListener('click', () => {
    const modal = document.getElementById('settings-modal');
    modal.classList.remove('hidden');
    // Load saved settings into toggles
    if (typeof initSettingsModal === 'function') {
        initSettingsModal();
    }
});

document.getElementById('btn-close-settings').addEventListener('click', () => {
    document.getElementById('settings-modal').classList.add('hidden');
});
document.getElementById('settings-overlay').addEventListener('click', () => {
    document.getElementById('settings-modal').classList.add('hidden');
});

// ─── Sync Files Button ──────
if (btnSyncFiles) {
    btnSyncFiles.addEventListener('click', () => {
        if (typeof syncFiles === 'function') {
            syncFiles();
        } else {
            showToast('Sync Files function not available', true);
        }
    });
}

// Load Dashboard Data
async function loadDashboardData(project) {
    try {
        currentDashboardProject = project || currentDashboardProject;
        const metricsRes = await fetch(`${API_BASE}/dashboard-data`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project })
        });
        const metricsData = await metricsRes.json();
        const conflictsRes = await fetch(`${API_BASE}/conflict-detection`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project })
        });
        const conflictsData = await conflictsRes.json();

        window.REQUIREWISE_DASHBOARD_DATA = metricsData.success ? (metricsData.data || {}) : {};
        window.REQUIREWISE_DASHBOARD_DATA.conflicts = conflictsData.success ? (conflictsData.conflicts || []) : [];

        if (typeof renderOverview === 'function') {
            renderOverview();
        }
        if (typeof renderConflicts === 'function') {
            const activeFilter = document.querySelector('.conflict-filter.active-filter')?.dataset.filter || 'all';
            renderConflicts(activeFilter);
        }

        const subtitle = document.getElementById('dash-project-name');
        if (subtitle && window.REQUIREWISE_DASHBOARD_DATA.project_name) {
            subtitle.textContent = window.REQUIREWISE_DASHBOARD_DATA.project_name;
            currentDashboardProject = window.REQUIREWISE_DASHBOARD_DATA.project_name;
        }

        updateWorkspaceSnapshot();

    } catch (error) {
        console.error('Failed to load dashboard data:', error);
        window.REQUIREWISE_DASHBOARD_DATA = { recent_activity: [{ text: `Dashboard load failed: ${error.message}`, time: 'just now', color: 'red', icon: '⚠️' }], conflicts: [] };
        if (typeof renderOverview === 'function') renderOverview();
        if (typeof renderConflicts === 'function') renderConflicts('all');
        updateWorkspaceSnapshot();
    }
}

// Integrations
btnSyncSlack.addEventListener('click', async () => {
    await triggerIntegration('slack', btnSyncSlack, '<div class="w-4 h-4 border-2 border-[#E01E5A] border-t-transparent rounded-full animate-spin"></div> Syncing...');
});

btnSyncGmail.addEventListener('click', async () => {
    await triggerIntegration('gmail', btnSyncGmail, '<div class="w-4 h-4 border-2 border-red-400 border-t-transparent rounded-full animate-spin"></div> Syncing...');
});

async function triggerIntegration(source, button, loadingMarkup) {
    const defaultMarkup = button.innerHTML;
    button.innerHTML = loadingMarkup;

    try {
        const response = await fetch(`${API_BASE}/trigger-integration`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project: projectSelect.value || '', source })
        });
        const payload = await response.json().catch(() => ({}));

        if (!response.ok || !payload.success) {
            throw new Error(payload.error || payload.message || `Failed to trigger ${source} integration.`);
        }

        showToast(payload.message || `${source} integration triggered successfully`);
    } catch (error) {
        showToast(error.message || `Failed to trigger ${source} integration`, true);
    } finally {
        button.innerHTML = defaultMarkup;
    }
}

// Toast Notification — also exposed globally for dashboard.js
function showToast(message, isError = false) {
    toastMsg.textContent = message;
    toast.classList.remove('translate-y-20', 'opacity-0');

    if (isError) {
        toast.classList.remove('border-primary');
        toast.classList.add('border-red-500');
        toast.querySelector('svg').classList.replace('text-primary', 'text-red-500');
    } else {
        toast.classList.add('border-primary');
        toast.classList.remove('border-red-500');
        toast.querySelector('svg').classList.replace('text-red-500', 'text-primary');
    }

    setTimeout(() => {
        toast.classList.add('translate-y-20', 'opacity-0');
    }, 3000);
}
window.showAppToast = showToast; // expose for dashboard.js

// ─── Lightweight Markdown Renderer ──────────────────────────────
// Converts Markdown text to styled HTML for the BRD Document Viewer.
// Handles headings, bold, italic, links, lists, code, blockquotes, and hr.
// Falls back to preformatted text if any conversion error occurs.
function renderMarkdown(md) {
    try {
        if (!md || typeof md !== 'string') return '<p class="text-gray-500 italic">No content available</p>';

        // ── Step 1: Extract markdown tables BEFORE any escaping ─────────
        // Matches consecutive lines that start and end with | (including separator rows)
        const tablePlaceholders = [];
        let processed = md.replace(/((?:^\|.+\|[ \t]*\n?)+)/gm, (tableBlock) => {
            try {
                const rows = tableBlock.trim().split('\n').filter(r => r.trim());
                if (rows.length < 2) return tableBlock; // Not a valid table (need header + separator at minimum)

                // Check if row 2 is the separator (e.g., |---|---|)
                const sepRow = rows[1];
                if (!/^\|[\s:-]+\|/.test(sepRow.trim())) return tableBlock;

                // Parse header cells
                const parseRow = (row) => row.replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
                const headers = parseRow(rows[0]);

                // Parse body rows (skip row 0=header, row 1=separator)
                const bodyRows = rows.slice(2).map(parseRow);

                // Build HTML table
                let tHtml = '<div class="overflow-x-auto my-3"><table class="w-full text-sm border-collapse">';
                tHtml += '<thead><tr>';
                headers.forEach(h => {
                    tHtml += `<th class="text-left text-xs font-semibold text-gray-300 uppercase tracking-wider px-3 py-2 border-b border-white/20 bg-white/5">${h}</th>`;
                });
                tHtml += '</tr></thead><tbody>';
                bodyRows.forEach((cells, i) => {
                    const rowBg = i % 2 === 0 ? '' : 'bg-white/[0.02]';
                    tHtml += `<tr class="${rowBg}">`;
                    cells.forEach(c => {
                        tHtml += `<td class="px-3 py-1.5 text-gray-300 border-b border-white/5">${c}</td>`;
                    });
                    tHtml += '</tr>';
                });
                tHtml += '</tbody></table></div>';

                // Store and replace with placeholder to protect from further regex
                const placeholder = `%%TABLE_${tablePlaceholders.length}%%`;
                tablePlaceholders.push(tHtml);
                return placeholder;
            } catch (tableErr) {
                // Table parse failed — leave the raw text intact for fallback rendering
                console.warn('Table parse fallback:', tableErr);
                return tableBlock;
            }
        });

        let html = processed
            // Escape raw HTML to prevent injection
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            // Code blocks (```...```) — must come before inline patterns
            .replace(/```([\s\S]*?)```/g, '<pre class="bg-black/50 border border-white/10 rounded-lg p-3 my-2 text-xs font-mono text-emerald-300 overflow-x-auto">$1</pre>')
            // Headings (# through ###### )
            .replace(/^######\s+(.*?)$/gm, '<h6 class="text-xs font-semibold text-gray-300 mt-3 mb-1">$1</h6>')
            .replace(/^#####\s+(.*?)$/gm, '<h5 class="text-sm font-semibold text-gray-300 mt-3 mb-1">$1</h5>')
            .replace(/^####\s+(.*?)$/gm, '<h4 class="text-sm font-bold text-gray-200 mt-4 mb-1">$1</h4>')
            .replace(/^###\s+(.*?)$/gm, '<h3 class="text-base font-bold text-white mt-4 mb-2">$1</h3>')
            .replace(/^##\s+(.*?)$/gm, '<h2 class="text-lg font-bold text-white mt-5 mb-2 pb-1 border-b border-white/10">$1</h2>')
            .replace(/^#\s+(.*?)$/gm, '<h1 class="text-xl font-bold text-white mt-6 mb-3 pb-2 border-b border-white/10">$1</h1>')
            // Bold + Italic combined
            .replace(/\*\*\*(.*?)\*\*\*/g, '<strong class="text-white"><em>$1</em></strong>')
            // Bold
            .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
            // Italic
            .replace(/\*(.*?)\*/g, '<em class="text-gray-300">$1</em>')
            // Inline code
            .replace(/`([^`]+)`/g, '<code class="px-1.5 py-0.5 rounded bg-white/10 text-emerald-400 text-xs font-mono">$1</code>')
            // Links
            .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener" class="text-primary hover:text-blue-300 underline">$1</a>')
            // Blockquotes
            .replace(/^&gt;\s+(.*?)$/gm, '<blockquote class="border-l-2 border-indigo-400/50 pl-3 my-2 text-sm text-gray-400 italic">$1</blockquote>')
            // Horizontal rules
            .replace(/^---+$/gm, '<hr class="border-white/10 my-4">')
            // Unordered list items (-, *, +)
            .replace(/^[\s]*[-*+]\s+(.*?)$/gm, '<li class="ml-4 text-sm text-gray-300 flex items-start gap-2 my-0.5"><span class="text-primary mt-0.5">•</span><span>$1</span></li>')
            // Ordered list items
            .replace(/^[\s]*(\d+)\.\s+(.*?)$/gm, '<li class="ml-4 text-sm text-gray-300 flex items-start gap-2 my-0.5"><span class="text-primary font-medium">$1.</span><span>$2</span></li>')
            // Double newlines as paragraph breaks
            .replace(/\n\n/g, '</p><p class="text-sm text-gray-300 mb-2">')
            // Single newlines as line breaks
            .replace(/\n/g, '<br>');

        // Wrap in paragraph
        html = '<p class="text-sm text-gray-300 mb-2">' + html + '</p>';

        // ── Step 2: Restore table placeholders with rendered HTML ───────
        tablePlaceholders.forEach((tHtml, i) => {
            html = html.replace(`%%TABLE_${i}%%`, tHtml);
        });

        return html;
    } catch (e) {
        // Fallback: show raw text in a preformatted block
        console.error('Markdown render error:', e);
        return `<pre class="text-sm text-gray-300 whitespace-pre-wrap">${md}</pre>`;
    }
}

// ─── displayBrdContent: Render BRD markdown in shared viewer ──────
// Scrolls the BRD Document Viewer into view and renders the provided
// markdown content. Used by BRD Generator, Updater, and Library Load.
// Handles string, object, and unexpected content types with fallback to plain text.
function displayBrdContent(title, markdownContent) {
    if (!brdContentViewer) return;
    const displayTitle = toSentenceCase(title);
    // Update label
    if (brdViewerLabel) brdViewerLabel.textContent = displayTitle;

    // Normalize content — ensure it's always a string before rendering
    let content = markdownContent;
    if (content === null || content === undefined) {
        content = '';
    } else if (typeof content === 'object') {
        // Object received (e.g. webhook returned structured data) — try to extract text
        content = content.text || content.content || content.markdown || content.raw || JSON.stringify(content, null, 2);
    } else {
        content = String(content);
    }

    // Render markdown with fallback to plain text on any error
    try {
        brdContentViewer.innerHTML = renderMarkdown(content);
    } catch (e) {
        console.error('displayBrdContent render error:', e);
        const escaped = content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        brdContentViewer.innerHTML = `<pre class="text-sm text-gray-300 whitespace-pre-wrap">${escaped}</pre>`;
    }

    // Scroll the viewer card into view smoothly
    if (brdViewerCard) {
        brdViewerCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

// ─── Helper: renderStructuredResult ────────────────────────────
// Renders MOM bullets, task list, and calendar events into a container.
// data = { summary, tasks: [...], calendar: [{title, time}], MOM: [...], raw: {...} }
function renderStructuredResult(container, data) {
    let html = '';
    // Minutes of Meeting
    if (data.MOM && data.MOM.length > 0) {
        html += '<p class="text-purple-400 font-medium text-[11px] uppercase tracking-wider mb-2">📝 Minutes of Meeting</p>';
        html += '<ul class="space-y-1 mb-3">' +
            data.MOM.map(item => {
                let content = item;
                if (typeof item === 'object' && item !== null) {
                    content = `<strong class="text-white">${item.topic || 'Topic'}</strong>: ${item.discussion_summary || item.decisions || JSON.stringify(item)}`;
                    if (item.owner) content += ` <em class="text-purple-300 ml-1 text-[10px]">(Owner: ${item.owner})</em>`;
                }
                return `
                <li class="flex items-start gap-2 bg-purple-500/5 p-1.5 rounded border border-purple-500/10">
                    <span class="text-purple-400 text-xs mt-0.5">•</span>
                    <span class="text-xs text-gray-300 w-full">${content}</span>
                </li>
            `}).join('') +
            '</ul>';
    }
    // Tasks
    if (data.tasks && data.tasks.length > 0) {
        html += '<p class="text-green-400 font-medium text-[11px] uppercase tracking-wider mb-2">📋 Tasks</p>';
        html += '<ul class="space-y-1 mb-3">' +
            data.tasks.map(task => {
                let content = task;
                if (typeof task === 'object' && task !== null) {
                    content = `<strong class="text-white">${task.task_title || 'Task'}</strong>: ${task.description || JSON.stringify(task)}`;
                    if (task.priority) content += ` <span class="bg-white/10 text-white px-1.5 py-0.5 rounded text-[10px] ml-1 uppercase">${task.priority}</span>`;
                }
                return `
                <li class="flex items-start gap-2 bg-white/5 p-1.5 rounded border border-white/5">
                    <svg class="w-3 h-3 text-green-400 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                    <span class="text-xs text-gray-300 w-full">${content}</span>
                </li>
            `}).join('') +
            '</ul>';
    }
    // Calendar events
    if (data.calendar && data.calendar.length > 0) {
        html += '<p class="text-blue-400 font-medium text-[11px] uppercase tracking-wider mb-2">📅 Calendar Events</p>';
        html += '<ul class="space-y-1 mb-3">' +
            data.calendar.map(evt => `
                <li class="flex items-start gap-2 bg-blue-500/5 p-1.5 rounded border border-blue-500/10">
                    <svg class="w-3 h-3 text-blue-400 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>
                    <span class="text-xs"><strong class="text-white">${evt.event_title || evt.title || 'Event'}</strong> — <span class="text-blue-300">${evt.event_date || evt.time || ''}</span></span>
                </li>
            `).join('') +
            '</ul>';
    }
    // Plain summary fallback (for responses that only have a text summary)
    if (data.summary && (!data.MOM || data.MOM.length === 0)) {
        html += `<p class="text-xs text-gray-300 whitespace-pre-wrap">${data.summary}</p>`;
    }
    container.innerHTML = html || '<p class="text-gray-500 italic text-center">No structured data returned</p>';
}

// ─── Helper: showCoreError ─────────────────────────────────────
// Shows an expandable error toast for core feature failures.
// Displays a brief title with an expandable detail section.
function showCoreError(title, detail) {
    // Show toast with the title
    showToast(title, true);
    // Also log to console for debugging
    console.error(`[Core Error] ${title}:`, detail);
}

/**
 * buildCrossFillText: Converts structured AI output (MOM, tasks, calendar, summary)
 * into a human-readable plain-text string suitable for cross-filling textareas.
 * This gives downstream BRD generation better context than raw transcript.
 */
function buildCrossFillText(data) {
    const parts = [];

    // Minutes of Meeting
    if (data.MOM && data.MOM.length > 0) {
        parts.push('Minutes of Meeting:');
        data.MOM.forEach((item, i) => {
            if (typeof item === 'object' && item !== null) {
                const topic = item.topic || 'Topic';
                const disc = item.discussion_summary || item.decisions || JSON.stringify(item);
                parts.push(`  ${i + 1}. ${topic}: ${disc}`);
            } else {
                parts.push(`  ${i + 1}. ${item}`);
            }
        });
    }

    // Tasks
    if (data.tasks && data.tasks.length > 0) {
        parts.push('\nTasks:');
        data.tasks.forEach((task, i) => {
            if (typeof task === 'object' && task !== null) {
                const title = task.task_title || 'Task';
                const desc = task.description || JSON.stringify(task);
                parts.push(`  ${i + 1}. ${title}: ${desc}`);
            } else {
                parts.push(`  ${i + 1}. ${task}`);
            }
        });
    }

    // Calendar events
    if (data.calendar && data.calendar.length > 0) {
        parts.push('\nCalendar Events:');
        data.calendar.forEach((evt, i) => {
            const title = evt.event_title || evt.title || 'Event';
            const date = evt.event_date || evt.time || '';
            parts.push(`  ${i + 1}. ${title} — ${date}`);
        });
    }

    // Fallback to plain summary if nothing structured
    if (parts.length === 0 && data.summary) {
        return data.summary;
    }

    return parts.join('\n');
}

// 1. Update BRD — N8N_WEBHOOK_UPDATE_BRD (uses filename from dropdown)
btnUpdateBrd.addEventListener('click', async () => {
    // Convert display name back to slug for the API; empty value = detect automatically
    const selectedValue = projectSelect.value;
    const filename = selectedValue ? toSlug(selectedValue) : '';
    const displayName = selectedValue ? toSentenceCase(selectedValue) : 'Auto-detect';

    // Read summary text from the new textarea
    const summary = updateBrdSummary ? updateBrdSummary.value.trim() : '';

    brdStatus.classList.remove('opacity-0', 'pointer-events-none');
    brdStatusText.textContent = `Updating BRD for ${displayName}...`;

    try {
        const response = await fetch(`${API_BASE}/update-brd`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename, summary })
        });

        const data = await response.json();

        brdStatus.classList.add('opacity-0', 'pointer-events-none');
        if (data.success) {
            showToast(`BRD updated successfully for ${displayName}`);
            // Extract returned BRD content and display in the shared viewer
            const responseData = data.data;
            const brdContent = (typeof responseData === 'string') ? responseData
                : (responseData?.text || responseData?.content || responseData?.markdown || '');
            if (brdContent) {
                displayBrdContent(selectedValue || 'updated-brd', brdContent);
            }
        } else {
            showToast(`BRD update failed: ${data.error || 'Unknown error'}`, true);
        }

        // Refresh dashboard data if open
        if (currentView === 'phase2') loadDashboardData(selectedValue || 'demo');

    } catch (error) {
        brdStatus.classList.add('opacity-0', 'pointer-events-none');
        showToast('Failed to update BRD', true);
    }
});

// 2. Meeting Transcripter — Uses AISummarization workflow (always real API)
btnSummarizeTranscript.addEventListener('click', async () => {
    const transcript = transcriptInput.value.trim();
    if (!transcript) {
        showToast('Please paste a transcript first', true);
        return;
    }

    btnSummarizeTranscript.innerHTML = '<div class="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin"></div>';
    btnSummarizeTranscript.disabled = true;

    let summaryData = null;
    try {
        const response = await fetch(`${API_BASE}/transcript-summary`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ transcript })
        });
        summaryData = await response.json();
    } catch (error) {
        summaryData = { success: false, error: error.message };
    }

    if (summaryData.success) {
        currentTranscriptSummary = summaryData.summary;
        // Render structured output: MOM → summary, Tasks, Calendar
        renderStructuredResult(transcriptResult, summaryData);
        transcriptResult.classList.remove('hidden');
        btnBrdFromTranscript.classList.remove('hidden');

        // Build a rich text summary from the structured output for cross-fill
        const crossFillText = buildCrossFillText(summaryData);

        // Auto-fill task assigner with original transcript (more detail for tasks)
        taskSummaryInput.value = transcript;
        // Cross-fill: Transcript output → BRD Generator text + Update BRD summary
        if (brdGeneratorText) brdGeneratorText.value = crossFillText;
        if (updateBrdSummary) updateBrdSummary.value = crossFillText;
        scrollToCard('card-update');
        showToast('Transcript analysed and BRD fields prefilled');
    } else {
        transcriptResult.classList.remove('hidden');
        transcriptResult.innerHTML = `<p class="text-red-400 text-sm">${summaryData.error || 'Transcript analysis failed.'}</p>`;
        btnBrdFromTranscript.classList.add('hidden');
        showCoreError('Transcript Analysis Failed', summaryData.error || 'Unknown error');
    }

    btnSummarizeTranscript.innerHTML = 'Extract Insights';
    btnSummarizeTranscript.disabled = false;
});

btnBrdFromTranscript.addEventListener('click', async () => {
    const selectedValue = projectSelect.value;
    const filename = selectedValue ? toSlug(selectedValue) : '';
    const displayName = selectedValue ? toSentenceCase(selectedValue) : 'Auto-detect';
    btnBrdFromTranscript.innerHTML = '<div class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mx-auto"></div>';

    try {
        const response = await fetch(`${API_BASE}/update-brd`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename, summary: currentTranscriptSummary })
        });

        const data = await response.json();
        if (data.success) {
            showToast(`BRD updated with transcript insights for ${displayName}`);
        } else {
            showToast(`BRD update failed: ${data.error || 'Unknown'}`, true);
        }
        if (currentView === 'phase2') loadDashboardData(selectedValue || 'demo');
    } catch (error) {
        showToast('Failed to update BRD', true);
    } finally {
        btnBrdFromTranscript.innerHTML = 'Update BRD with Insights';
    }
});

// 3. Meeting Recorder
btnRecord.addEventListener('click', async () => {
    if (!isRecording) {
        // Start recording
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];

            mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) audioChunks.push(e.data);
            };

            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                await processAudio(audioBlob);
            };

            mediaRecorder.start();
            isRecording = true;

            // UI Updates
            recordIcon.classList.add('rounded-lg', 'scale-50');
            recordPulse.classList.remove('hidden');
            recordStatus.textContent = 'Recording... Click to stop';
            recordStatus.classList.add('text-red-400', 'animate-pulse');
            setAudioCaptureNote('Recording live audio. When you stop, RequireWise will send it for transcription and structured analysis.');

        } catch (error) {
            console.error('Microphone access denied:', error);
                audioResult.innerHTML = `
                    <div class="rounded-xl border border-red-500/20 bg-red-500/10 p-4 text-left">
                        <p class="text-sm font-semibold text-red-300 mb-1">Microphone access blocked</p>
                        <p class="text-xs text-gray-300 leading-relaxed">Allow microphone access in the browser or switch to transcript-based input. Live audio also requires a configured speech-to-text provider on the backend.</p>
                    </div>
                `;
                audioResult.classList.remove('hidden');
                setAudioCaptureNote('Microphone access is unavailable. Use transcript-based flows or enable mic permission and try again.');
                showToast('Microphone access denied', true);
        }
    } else {
        // Stop recording
        mediaRecorder.stop();
        mediaRecorder.stream.getTracks().forEach(track => track.stop());
        isRecording = false;

        // UI Updates
        recordIcon.classList.remove('rounded-lg', 'scale-50');
        recordPulse.classList.add('hidden');
        recordStatus.textContent = 'Processing audio...';
        recordStatus.classList.remove('text-red-400', 'animate-pulse');
        recordStatus.classList.add('text-primary');
        setAudioCaptureNote('Sending your recording for transcription and structured extraction.');
    }
});

function setAudioCaptureNote(message) {
    const note = document.getElementById('audio-capture-note');
    if (note) {
        note.textContent = message;
    }
}

async function processAudio(audioBlob) {
    let summaryData = null;
    // Always use real API: send audio to /api/audio-summary (transcribe → summarize)
    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.webm');
    try {
        const response = await fetch(`${API_BASE}/audio-summary`, {
            method: 'POST',
            body: formData
        });
        summaryData = await response.json();
    } catch (error) {
        summaryData = { success: false, error: error.message };
    }

    if (summaryData && summaryData.success) {
        currentAudioSummary = summaryData.summary;
        // Show speaker transcript first
        if (summaryData.transcript) {
            const speakers = Object.entries(summaryData.transcript).map(
                ([k, v]) => `<span class="text-primary font-medium">${k}:</span> ${v}`
            ).join('<br>');
            audioResult.innerHTML = `
                <p class="text-red-400 font-medium mb-1">🎙 Speaker Transcript:</p>
                <div class="text-xs mb-3 p-2 rounded bg-white/5">${speakers}</div>
                <hr class="border-white/10 my-2">
            `;
        } else {
            audioResult.innerHTML = '';
        }
        // Append structured result (MOM, tasks, calendar)
        const structuredDiv = document.createElement('div');
        renderStructuredResult(structuredDiv, summaryData);
        audioResult.appendChild(structuredDiv);
        audioResult.classList.remove('hidden');
        btnBrdFromAudio.classList.remove('hidden');
        let rawTranscriptText = summaryData.summary;
        if (summaryData.transcript) {
            rawTranscriptText = Object.entries(summaryData.transcript).map(([speaker, text]) =>
                `${speaker}: ${text}`
            ).join('\n');
        }

        // Build a rich text summary from the structured output for cross-fill
        const crossFillText = buildCrossFillText(summaryData);

        // Cross-fill: Recording output → Meeting Transcript input + BRD Generator + Update BRD
        // Fill the meeting transcript textarea so user can further analyse it
        if (transcriptInput) transcriptInput.value = rawTranscriptText;
        // Auto-fill task assigner with raw transcript (more detail for tasks)
        taskSummaryInput.value = rawTranscriptText;
        // Fill BRD-related fields with the structured summary
        if (brdGeneratorText) brdGeneratorText.value = crossFillText;
        if (updateBrdSummary) updateBrdSummary.value = crossFillText;
        recordStatus.textContent = 'Click to start recording';
        recordStatus.classList.remove('text-primary');
        setAudioCaptureNote('Audio summary is ready. Review the output or push the extracted context into the BRD updater.');
        scrollToCard('card-update');
        showToast('Audio processed and BRD updater prefilled');
    } else {
        audioResult.innerHTML = `<p class="text-red-400 font-medium mb-1">Audio processing failed</p><p class="text-xs text-gray-300">${summaryData?.error || 'Unable to extract speaker data from this recording.'}</p>`;
        audioResult.classList.remove('hidden');
        btnBrdFromAudio.classList.add('hidden');
        recordStatus.textContent = 'Click to start recording';
        recordStatus.classList.remove('text-primary');
        setAudioCaptureNote('Audio processing failed. Check STT provider configuration or switch to transcript-based input.');
        showCoreError('Audio Processing Failed', summaryData?.error || 'Unknown error');
    }
}

btnBrdFromAudio.addEventListener('click', async () => {
    const selectedValue = projectSelect.value;
    const filename = selectedValue ? toSlug(selectedValue) : '';
    const displayName = selectedValue ? toSentenceCase(selectedValue) : 'Auto-detect';
    btnBrdFromAudio.innerHTML = '<div class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mx-auto"></div>';

    try {
        const response = await fetch(`${API_BASE}/update-brd`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename, summary: currentAudioSummary })
        });

        const data = await response.json();
        if (data.success) {
            showToast(`BRD updated with audio insights for ${displayName}`);
        } else {
            showToast(`BRD update failed: ${data.error || 'Unknown'}`, true);
        }
        if (currentView === 'phase2') loadDashboardData(selectedValue || 'demo');
    } catch (error) {
        showToast('Failed to update BRD', true);
    } finally {
        btnBrdFromAudio.innerHTML = 'Update BRD';
    }
});

// 4. Task Assigner — Uses AISummarization → extracts Tasks + Calendar
//    After tasks are shown, user can trigger Google Tools to schedule events
let lastTaskResult = null; // store for Google Tools button

btnAssignTasks.addEventListener('click', async () => {
    const summary = taskSummaryInput.value.trim();
    if (!summary) {
        showToast('Please enter a summary first', true);
        return;
    }

    btnAssignTasks.innerHTML = '<div class="w-5 h-5 border-2 border-green-400 border-t-transparent rounded-full animate-spin mx-auto"></div>';
    btnAssignTasks.disabled = true;

    let taskData = null;
    // Always use real API: call /api/assign-tasks (AISummarization)
    try {
        const response = await fetch(`${API_BASE}/assign-tasks`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ summary })
        });
        taskData = await response.json();
    } catch (error) {
        taskData = { success: false, error: error.message };
    }

    if (taskData && taskData.success) {
        lastTaskResult = taskData;
        // Render tasks
        let html = '';
        if (taskData.tasks && taskData.tasks.length > 0) {
            html += '<p class="text-green-400 font-medium text-[11px] uppercase tracking-wider mb-2">📋 Tasks</p>';
            html += '<ul class="space-y-1.5 mb-3">' +
                taskData.tasks.map(task => {
                    let content = task;
                    if (typeof task === 'object' && task !== null) {
                        content = `<strong class="text-white">${task.task_title || 'Task'}</strong>: ${task.description || JSON.stringify(task)}`;
                        if (task.priority) content += ` <span class="bg-white/10 text-white px-1.5 py-0.5 rounded text-[10px] ml-1 uppercase">${task.priority}</span>`;
                    }
                    return `
                    <li class="flex items-start gap-2 bg-white/5 p-2 rounded border border-white/5">
                        <svg class="w-3.5 h-3.5 text-green-400 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                        <span class="text-xs text-gray-200 w-full">${content}</span>
                    </li>
                `}).join('') +
                '</ul>';
        }
        // Render calendar events
        if (taskData.calendar && taskData.calendar.length > 0) {
            html += '<p class="text-blue-400 font-medium text-[11px] uppercase tracking-wider mb-2">📅 Calendar Events</p>';
            html += '<ul class="space-y-1.5 mb-3">' +
                taskData.calendar.map(evt => `
                    <li class="flex items-start gap-2 bg-blue-500/5 p-2 rounded border border-blue-500/10">
                        <svg class="w-3.5 h-3.5 text-blue-400 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>
                        <span class="text-xs"><strong class="text-white">${evt.event_title || evt.title || 'Event'}</strong> — ${evt.event_date || evt.time || ''}</span>
                    </li>
                `).join('') +
                '</ul>';
        }
        // Google Tools button
        html += `
            <button id="btn-google-tools" class="w-full py-2 mt-1 rounded-lg bg-yellow-500/15 hover:bg-yellow-500/25 text-yellow-400 border border-yellow-500/30 transition-all font-medium text-xs flex items-center justify-center gap-2">
                <svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24"><path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/><path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/></svg>
                Send to Google (Calendar + Email)
            </button>
        `;
        tasksResult.innerHTML = html;
        // Bind Google Tools button
        document.getElementById('btn-google-tools')?.addEventListener('click', triggerGoogleTools);
        scrollToCard('card-tasks');
        showToast('Tasks extracted successfully');
    } else {
        showCoreError('Task Extraction Failed', taskData?.error || 'Unknown error');
        tasksResult.innerHTML = '<p class="text-gray-500 italic text-center mt-4">No tasks generated</p>';
    }

    btnAssignTasks.innerHTML = 'Generate Tasks';
    btnAssignTasks.disabled = false;
});

// ─── Google Tools Integration ──────
// Sends tasks, calendar events, and MOM to Google (create events + email)
async function triggerGoogleTools() {
    const btn = document.getElementById('btn-google-tools');
    if (!btn || !lastTaskResult) return;
    btn.innerHTML = '<div class="w-3.5 h-3.5 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin"></div> Sending...';
    btn.disabled = true;

    try {
        const response = await fetch(`${API_BASE}/google-tools`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                recipients: [
                    "khem.chand@indiamart.com",
                    "paras.lehana@indiamart.com",
                    "abhinav.kaushik@indiamart.com"
                ],
                calender: lastTaskResult.calendar || [],
                Task: lastTaskResult.tasks || [],
                MOM: lastTaskResult.MOM || []
            })
        });
        const data = await response.json();
        if (data.success) {
            showToast(data.message || 'Google events created and emails sent!');
            btn.innerHTML = '✅ Sent to Google!';
            btn.classList.replace('text-yellow-400', 'text-green-400');
            btn.classList.replace('border-yellow-500/30', 'border-green-500/30');
            btn.classList.replace('bg-yellow-500/15', 'bg-green-500/15');
        } else {
            showCoreError('Google Tools Failed', data.error || 'Unknown error');
            btn.innerHTML = '⚠️ Failed — Retry';
            btn.disabled = false;
        }
    } catch (error) {
        showCoreError('Google Tools Failed', error.message);
        btn.innerHTML = '⚠️ Failed — Retry';
        btn.disabled = false;
    }
}

// ─── BRD Generator: Create New BRD ────────────────────────────
// Submits a new BRD via POST /api/new-brd. The webhook now returns the
// BRD content as markdown text directly — no polling needed.
btnGenerateBrd.addEventListener('click', async () => {
    const text = brdGeneratorText.value.trim();
    const rawFilename = brdGeneratorFilename.value.trim();

    if (!text) {
        showToast('Please describe your project requirements first', true);
        return;
    }
    if (!rawFilename) {
        showToast('Please provide a filename for the BRD', true);
        return;
    }

    const slug = toSlug(rawFilename);
    if (!slug) {
        showToast('Invalid filename — use letters, numbers, spaces or hyphens', true);
        return;
    }

    // Always append '-brd' suffix to generated filenames for consistency
    const finalSlug = slug.endsWith('-brd') ? slug : `${slug}-brd`;

    // Disable button and show progress
    btnGenerateBrd.disabled = true;
    btnGenerateBrd.innerHTML = '<div class="w-4 h-4 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin"></div> Generating...';
    brdGeneratorStatus.classList.remove('hidden');
    brdGeneratorStatusText.textContent = 'Submitting BRD request...';
    brdGeneratorProgress.style.width = '20%';

    try {
        // Submit the new BRD creation request — response includes markdown content
        const createRes = await fetch(`${API_BASE}/new-brd`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: finalSlug, text })
        });
        const createData = await createRes.json();

        brdGeneratorProgress.style.width = '90%';

        if (!createData.success) {
            showToast(`BRD creation failed: ${createData.error || 'Unknown error'}`, true);
            resetBrdGeneratorUI();
            brdGeneratorStatus.classList.add('hidden');
            return;
        }

        brdGeneratorProgress.style.width = '100%';
        if (createData.source === 'llm-agent') {
            brdGeneratorStatusText.textContent = '✅ BRD generated via LLM agent.';
        } else {
            brdGeneratorStatusText.textContent = '✅ BRD Created Successfully!';
        }

        // Extract markdown content from the response
        // The n8n webhook returns the BRD text in the response data
        const responseData = createData.data;
        const brdContent = (typeof responseData === 'string') ? responseData
            : (responseData?.text || responseData?.content || responseData?.markdown || '');

        if (brdContent) {
            // Render the BRD content in the shared Document Viewer
            displayBrdContent(finalSlug, brdContent);
        }

        if (createData.warning) {
            showToast(createData.warning);
        } else if (createData.source === 'llm-agent') {
            showToast(`BRD "${toSentenceCase(finalSlug)}" generated by the LLM agent.`);
        } else {
            showToast(`BRD "${toSentenceCase(finalSlug)}" created successfully!`);
        }

        // Refresh the dropdown to include the new BRD
        await refreshBrdDropdown();
        // Select the newly created BRD in the dropdown
        projectSelect.value = finalSlug;

        // Also refresh the BRD Library
        loadBrdLibrary();
        updateWorkspaceSnapshot();

        // Hide status after a brief display
        setTimeout(() => {
            brdGeneratorStatus.classList.add('hidden');
        }, 3000);

    } catch (error) {
        showToast(`BRD creation failed: ${error.message}`, true);
        brdGeneratorStatus.classList.add('hidden');
    } finally {
        resetBrdGeneratorUI();
    }
});

function resetBrdGeneratorUI() {
    btnGenerateBrd.disabled = false;
    btnGenerateBrd.innerHTML = `
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path>
        </svg>
        Generate BRD`;
}

// ─── BRD Library: Browse & Load Existing BRDs ─────────────────
// Loads all BRDs from /api/list-brds and displays them with Load BRD buttons.
// Each BRD item shows: name, Google Docs link, and Load BRD button.
// The Load BRD button renders the BRD `content` in the shared Document Viewer.
const brdLibraryList = document.getElementById('brd-library-list');
const btnRefreshLibrary = document.getElementById('btn-refresh-library');
const brdLibrarySearch = document.getElementById('brd-library-search');
let cachedBrdLibrary = [];
let brdLibrarySearchTimer = null;

function renderBrdLibrary(brds, query = '') {
    if (!brdLibraryList) return;

    const normalizedQuery = (query || '').trim().toLowerCase();
    const filtered = normalizedQuery
        ? brds.filter(brd => {
            const name = typeof brd === 'string' ? brd : (brd.name || brd.filename || '');
            return name.toLowerCase().includes(normalizedQuery);
        })
        : brds;

    if (!filtered.length) {
        brdLibraryList.innerHTML = '<p class="text-gray-500 italic text-center mt-4">No BRDs matched your search.</p>';
        return;
    }

    brdLibraryList.innerHTML = '<ul class="space-y-2">' +
        filtered.map(brd => {
            const name = typeof brd === 'string' ? brd : (brd.name || brd.filename || JSON.stringify(brd));
            const preview = (typeof brd === 'object' && brd.preview) ? brd.preview : '';
            const content = (typeof brd === 'object' && brd.content) ? brd.content : '';
            const displayName = toSentenceCase(name);
            const contentAttr = content ? ` data-content="${btoa(unescape(encodeURIComponent(content)))}"` : '';
            return `
                <li class="flex items-center gap-2 px-3 py-2 rounded-lg bg-white/5 border border-white/5 hover:border-cyan-500/30 transition-all">
                    <svg class="w-4 h-4 text-cyan-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                    </svg>
                    <span class="flex-1 text-sm text-gray-300 font-medium">${displayName}</span>
                    ${preview ? `
                    <a href="${preview}" target="_blank" rel="noopener noreferrer"
                       class="px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-xs text-gray-400 hover:text-white border border-white/10 transition-all flex items-center gap-1"
                       title="Open in Google Docs">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
                        Docs
                    </a>` : ''}
                    <button class="brd-load-btn px-2 py-1 rounded bg-indigo-500/15 hover:bg-indigo-500/25 text-xs text-indigo-300 hover:text-white border border-indigo-500/30 transition-all flex items-center gap-1"
                            data-name="${name}"${contentAttr}>
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path></svg>
                        Load BRD
                    </button>
                </li>
            `;
        }).join('') +
        '</ul>';

    brdLibraryList.querySelectorAll('.brd-load-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const name = btn.dataset.name;
            const encodedContent = btn.dataset.content;
            if (encodedContent) {
                const content = decodeURIComponent(escape(atob(encodedContent)));
                displayBrdContent(name, content);
            } else {
                showToast('No BRD content available yet. Content will be available after the next refresh.', true);
            }
        });
    });
}

/**
 * Loads the full BRD list and renders clickable items in the library panel.
 * The list-brds response includes {id, name, preview, content} for each BRD.
 * - preview: Google Docs URL for opening the document externally
 * - content: Markdown text of the BRD for in-page viewing
 */
async function loadBrdLibrary() {
    if (!brdLibraryList) return;
    brdLibraryList.innerHTML = '<p class="text-gray-500 italic text-center mt-4">Loading BRDs...</p>';

    try {
        const response = await fetch(`${API_BASE}/list-brds`);
        const data = await response.json();

        if (data.success && data.brds && data.brds.length > 0) {
            cachedBrdLibrary = data.brds;
            renderBrdLibrary(cachedBrdLibrary, brdLibrarySearch ? brdLibrarySearch.value : '');
        } else {
            cachedBrdLibrary = [];
            brdLibraryList.innerHTML = '<p class="text-gray-500 italic text-center mt-4">No BRDs found. Generate one above!</p>';
        }
        updateWorkspaceSnapshot();
    } catch (error) {
        console.error('Failed to load BRD library:', error);
        brdLibraryList.innerHTML = '<p class="text-red-400 italic text-center mt-4">Failed to load BRD list</p>';
        updateWorkspaceSnapshot();
    }
}

async function searchBrdLibrary(query) {
    const normalizedQuery = (query || '').trim();
    if (!normalizedQuery) {
        renderBrdLibrary(cachedBrdLibrary, '');
        return;
    }

    renderBrdLibrary(cachedBrdLibrary, normalizedQuery);

    const localMatches = cachedBrdLibrary.filter(brd => {
        const name = typeof brd === 'string' ? brd : (brd.name || brd.filename || '');
        return name.toLowerCase().includes(normalizedQuery.toLowerCase());
    });
    if (localMatches.length) {
        return;
    }

    brdLibraryList.innerHTML = '<p class="text-gray-500 italic text-center mt-4">Searching BRD library...</p>';

    try {
        const response = await fetch(`${API_BASE}/list-brds?filename=${encodeURIComponent(toSlug(normalizedQuery))}`);
        const data = await response.json();

        if (data.success && Array.isArray(data.brds) && data.brds.length) {
            renderBrdLibrary(data.brds, normalizedQuery);
            return;
        }

        renderBrdLibrary([], normalizedQuery);
    } catch (error) {
        console.error('Failed to search BRD library:', error);
        brdLibraryList.innerHTML = '<p class="text-red-400 italic text-center mt-4">Failed to search BRD library</p>';
    }
}

// Refresh Library button handler
if (btnRefreshLibrary) {
    btnRefreshLibrary.addEventListener('click', loadBrdLibrary);
}

if (brdLibrarySearch) {
    brdLibrarySearch.addEventListener('input', () => {
        clearTimeout(brdLibrarySearchTimer);
        brdLibrarySearchTimer = setTimeout(() => {
            searchBrdLibrary(brdLibrarySearch.value);
        }, 250);
    });
}

// ─── OpenProject Tickets ──────────────────────────────────────
// Fetches work packages from the configured OpenProject instance,
// displays them as cards, and provides "Use as BRD Update" action
// to push ticket content into the Update BRD form.

// Store fetched tickets globally so onclick handlers can reference by index
// This avoids messy base64/inline JSON in HTML attributes
let fetchedTickets = [];

/**
 * useTicketForBrdUpdate: Takes ticket data from OpenProject and fills it into the
 * Update BRD section — populates the summary textarea with a structured prompt built
 * from the ticket's subject, description, priority, and status. Then scrolls to the
 * Update BRD card so the user can review and trigger the sync.
 * @param {number} index - Index into fetchedTickets array
 */
function useTicketForBrdUpdate(index) {
    const ticket = fetchedTickets[index];
    if (!ticket) return;

    // Build a structured summary from ticket fields for the BRD updater
    // This gives the AI enough context to produce a meaningful BRD update
    const parts = [];
    parts.push(`## OpenProject Ticket #${ticket.id}: ${ticket.subject}`);
    if (ticket.priority) parts.push(`**Priority:** ${ticket.priority}`);
    if (ticket.status) parts.push(`**Status:** ${ticket.status}`);
    if (ticket.type) parts.push(`**Type:** ${ticket.type}`);
    if (ticket.assignee && ticket.assignee !== 'Unassigned') parts.push(`**Assignee:** ${ticket.assignee}`);
    parts.push(''); // blank line before description
    if (ticket.description) {
        parts.push(`### Description`);
        parts.push(ticket.description);
    } else {
        parts.push('_No description provided in the ticket._');
    }
    const summaryText = parts.join('\n');

    // Decode HTML entities (e.g. &gt; → >) so textarea shows clean text
    const decoded = summaryText.replace(/&gt;/g, '>').replace(/&lt;/g, '<').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'");

    // Fill the Update BRD summary textarea
    if (updateBrdSummary) {
        updateBrdSummary.value = decoded;
        updateBrdSummary.focus();
    }

    // Scroll to the Update BRD card (find parent .bento-item of the update button)
    const updateBrdCard = btnUpdateBrd?.closest('.bento-item');
    if (updateBrdCard) {
        updateBrdCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
        // Brief highlight animation to draw user's attention
        updateBrdCard.classList.add('ring-2', 'ring-primary/60');
        setTimeout(() => updateBrdCard.classList.remove('ring-2', 'ring-primary/60'), 2000);
    }

    showToast(`Ticket #${ticket.id} loaded into Update BRD — review and click "Sync Requirements"`);
}

/**
 * previewTicket: Shows the ticket description in the BRD Document Viewer panel
 * using the shared markdown renderer.
 * @param {number} index - Index into fetchedTickets array
 */
function previewTicket(index) {
    const ticket = fetchedTickets[index];
    if (!ticket) return;
    const title = `Ticket #${ticket.id}: ${ticket.subject}`;
    const content = ticket.description || '_No description available._';
    displayBrdContent(title, content);
}

if (btnFetchTickets) {
    btnFetchTickets.addEventListener('click', async () => {
        btnFetchTickets.innerHTML = '<div class="w-4 h-4 border-2 border-orange-400 border-t-transparent rounded-full animate-spin"></div> Fetching...';
        btnFetchTickets.disabled = true;

        try {
            const response = await fetch(`${API_BASE}/openproject-tickets`);
            const data = await response.json();

            if (data.success && data.tickets && data.tickets.length > 0) {
                // Store tickets globally for button handlers
                fetchedTickets = data.tickets;

                // Show count badge
                if (ticketCountBadge) {
                    ticketCountBadge.textContent = `${data.tickets.length} tickets`;
                    ticketCountBadge.classList.remove('hidden');
                }

                // Render tickets as cards with action buttons
                ticketsResult.innerHTML = '<div class="space-y-3">' +
                    data.tickets.map((ticket, idx) => {
                        const statusColor = (ticket.status || '').toLowerCase().includes('closed') ? 'green' :
                            (ticket.status || '').toLowerCase().includes('progress') ? 'blue' : 'orange';
                        return `
                            <div class="p-3 rounded-lg bg-white/5 border border-white/5 hover:border-orange-500/20 transition-all">
                                <div class="flex items-start justify-between gap-2 mb-1">
                                    <span class="text-sm font-medium text-white">#${ticket.id} ${ticket.subject}</span>
                                    <span class="px-2 py-0.5 rounded-full bg-${statusColor}-500/15 text-${statusColor}-400 text-[10px] font-medium whitespace-nowrap">${ticket.status || 'Unknown'}</span>
                                </div>
                                <div class="flex gap-3 text-[11px] text-gray-400 mb-1">
                                    ${ticket.type ? `<span class="flex items-center gap-1">📋 ${ticket.type}</span>` : ''}
                                    ${ticket.priority ? `<span class="flex items-center gap-1">⚡ ${ticket.priority}</span>` : ''}
                                    ${ticket.assignee ? `<span class="flex items-center gap-1">👤 ${ticket.assignee}</span>` : ''}
                                </div>
                                ${ticket.description ? `<p class="text-xs text-gray-500 mt-1 mb-2 line-clamp-3">${ticket.description.substring(0, 300).replace(/</g, '&lt;').replace(/>/g, '&gt;')}${ticket.description.length > 300 ? '...' : ''}</p>` : ''}
                                <div class="flex gap-2 mt-2">
                                    <button onclick="useTicketForBrdUpdate(${idx})"
                                        class="px-3 py-1.5 rounded-md bg-primary/20 hover:bg-primary/30 text-primary border border-primary/30 transition-all text-xs font-medium flex items-center gap-1.5"
                                        title="Fill ticket content into Update BRD form">
                                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path>
                                        </svg>
                                        Use as BRD Update
                                    </button>
                                    <button onclick="previewTicket(${idx})"
                                        class="px-3 py-1.5 rounded-md bg-white/5 hover:bg-white/10 text-gray-400 border border-white/10 transition-all text-xs font-medium flex items-center gap-1.5"
                                        title="Preview ticket description in the document viewer">
                                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path>
                                        </svg>
                                        Preview
                                    </button>
                                </div>
                            </div>
                        `;
                    }).join('') +
                    '</div>';
                showToast(`Loaded ${data.tickets.length} tickets from OpenProject`);
            } else {
                ticketsResult.innerHTML = `<p class="text-gray-500 italic text-center mt-4">${data.error || 'No tickets found'}</p>`;
                if (data.error) showToast(data.error, true);
            }
        } catch (error) {
            console.error('Failed to fetch tickets:', error);
            ticketsResult.innerHTML = '<p class="text-red-400 italic text-center mt-4">Failed to fetch tickets from OpenProject</p>';
            showToast('Failed to fetch OpenProject tickets', true);
        } finally {
            btnFetchTickets.innerHTML = `
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path>
                </svg>
                Fetch Tickets`;
            btnFetchTickets.disabled = false;
        }
    });
}

// Run init
init();

// Load BRD Library on page load (after init so dropdown is ready)
loadBrdLibrary();
