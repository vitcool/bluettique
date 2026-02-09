const statusView = document.getElementById('statusView');
const logView = document.getElementById('logView');
const logSections = document.getElementById('logSections');
const refreshLogsBtn = document.getElementById('refreshLogsBtn');
const logTitle = document.getElementById('logTitle');
const viewButtons = document.querySelectorAll('.view-toggle button');
const statusViewBtn = document.querySelector('.view-toggle button[data-view="status"]');
const topbar = document.querySelector('.topbar');

const boilerCard = document.getElementById('boilerCard');
const boilerCardValue = document.getElementById('boilerCardValue');
const boilerCardMeta = document.getElementById('boilerCardMeta');
const boilerCardMeta2 = document.getElementById('boilerCardMeta2');
const acStatus = document.getElementById('acStatus');
const batteryPercentEl = document.getElementById('batteryPercent');
const batteryTime = document.getElementById('batteryTime');
const batteryExtra = document.getElementById('batteryExtra');
const inputStatus = document.getElementById('inputStatus');
const inputDetail = document.getElementById('inputDetail');
const connStatus = document.getElementById('connStatus');
const connDetail = document.getElementById('connDetail');
const acOutputDetail = document.getElementById('acOutputDetail');
const chargingStateValue = document.getElementById('chargingStateValue');
const chargingStateMeta = document.getElementById('chargingStateMeta');

const DEFAULT_STATUS_REFRESH_MS = 2000;
const DEFAULT_LOG_REFRESH_MS = 2000;
const DEFAULT_LOG_LIMIT = 800;
const MAX_UI_LOG_LINES = 5000;
const urlParams = new URLSearchParams(window.location.search);
let connectionWindowMin = (() => {
    const val = Number(urlParams.get('conn_window_min'));
    if (Number.isFinite(val) && val > 0) return val;
    return 5;
})();

let currentView = 'status';
let logFetchController = null;
let logFetchInFlight = false;
let logRefreshTimer = null;
let statusRefreshTimer = null;
let statusRefreshMs = DEFAULT_STATUS_REFRESH_MS;
let logRefreshMs = DEFAULT_LOG_REFRESH_MS;
const LOG_VIEW_TO_SOURCE = {
    'boiler-log': 'boiler',
    'charging-log': 'charging'
};
const logSourceState = {
    boiler: { lines: [], file: 'boiler.log', latestTs: null, initialized: false },
    charging: { lines: [], file: 'log.txt', latestTs: null, initialized: false }
};

function isDesktopLayout() {
    const width = window.innerWidth || document.documentElement.clientWidth || 0;
    const coarsePointer = window.matchMedia('(pointer: coarse)').matches;
    const touchDevice = coarsePointer || (navigator.maxTouchPoints || 0) > 0;

    // Always desktop on clearly wide screens; otherwise only for non-touch layouts.
    if (width >= 980) return true;
    if (touchDevice) return false;
    return width >= 760;
}

function clearLogSections() {
    logSections.innerHTML = '';
}

function setLogTitle(label, file) {
    if (!logTitle) return;
    if (!label && !file) {
        logTitle.textContent = 'Logs';
        return;
    }
    if (label && file) {
        logTitle.textContent = `${label} (${file})`;
        return;
    }
    logTitle.textContent = label || file || 'Logs';
}

function renderLogTextMessage(message) {
    setLogTitle('Logs', null);
    clearLogSections();
    const pre = document.createElement('pre');
    pre.id = 'logContent';
    pre.textContent = message;
    logSections.appendChild(pre);
}

function appendLogSourceSection(label, file, lines) {
    const section = document.createElement('section');
    section.className = 'log-source';

    const header = document.createElement('div');
    header.className = 'log-source-header';
    header.textContent = `${label} (${file})`;

    const pre = document.createElement('pre');
    pre.textContent = lines.length ? lines.join('\n') : '(no lines)';

    section.appendChild(header);
    section.appendChild(pre);
    logSections.appendChild(section);
}

function renderLogSources(sources) {
    clearLogSections();
    sources.forEach(source => {
        const label = source?.label || 'log';
        const file = source?.file || 'unknown';
        const lines = Array.isArray(source?.lines) ? [...source.lines].reverse() : [];
        if (source === sources[0]) {
            setLogTitle(label, file);
        }
        appendLogSourceSection(label, file, lines);
    });
}

function renderSingleLogSource(source) {
    if (!source) {
        renderLogTextMessage('No logs available.');
        return;
    }
    renderLogSources([source]);
}

function getCurrentLogViewport() {
    const pre = logSections.querySelector('.log-source pre, pre#logContent');
    if (!pre) return null;

    const maxScrollTop = Math.max(0, pre.scrollHeight - pre.clientHeight);
    const offsetFromBottom = Math.max(0, maxScrollTop - pre.scrollTop);
    return {
        nearTop: pre.scrollTop <= 24,
        offsetFromBottom,
        nearBottom: offsetFromBottom <= 24
    };
}

function restoreLogViewport(viewport) {
    if (!viewport) return;
    const pre = logSections.querySelector('.log-source pre, pre#logContent');
    if (!pre) return;

    if (viewport.nearTop) {
        pre.scrollTop = 0;
        return;
    }

    if (viewport.nearBottom) {
        pre.scrollTop = pre.scrollHeight;
        return;
    }

    const maxScrollTop = Math.max(0, pre.scrollHeight - pre.clientHeight);
    pre.scrollTop = Math.max(0, maxScrollTop - viewport.offsetFromBottom);
}

function getLogState(source) {
    return logSourceState[source] || null;
}

function updateLogStateFromSource(source, payload, mode = 'replace') {
    const state = getLogState(source);
    if (!state || !payload) return null;

    const incomingLines = Array.isArray(payload.lines) ? payload.lines : [];
    const file = payload.file || state.file || `${source}.log`;

    if (mode === 'append') {
        if (incomingLines.length) {
            const dedupeWindow = state.lines.slice(-2000);
            const dedupeSet = new Set(dedupeWindow);
            const uniqueIncoming = incomingLines.filter(line => !dedupeSet.has(line));
            state.lines = [...state.lines, ...uniqueIncoming];
        }
    } else {
        state.lines = [...incomingLines];
    }

    if (state.lines.length > MAX_UI_LOG_LINES) {
        state.lines = state.lines.slice(-MAX_UI_LOG_LINES);
    }

    if (payload.latest_ts) {
        state.latestTs = payload.latest_ts;
    }
    state.file = file;
    state.initialized = true;
    return state;
}

function renderLogState(source) {
    const state = getLogState(source);
    if (!state) {
        renderLogTextMessage('No logs available.');
        return;
    }
    const viewport = getCurrentLogViewport();
    renderSingleLogSource({
        label: source,
        file: state.file || `${source}.log`,
        lines: state.lines
    });
    restoreLogViewport(viewport);
}

function buildLogsUrl(source, opts = {}) {
    const params = new URLSearchParams({
        limit: String(DEFAULT_LOG_LIMIT),
        source
    });
    if (opts.since) {
        params.set('since', opts.since);
    }
    return `/api/logs?${params.toString()}`;
}

function parseLegacyCombinedLogs(rawLogs) {
    const sections = [];
    let current = null;
    const lines = rawLogs.split('\n');
    const headerRe = /^=====\\s*(.+?)\\s*\\((.+?)\\)\\s*=====$/;

    for (const line of lines) {
        const m = line.match(headerRe);
        if (m) {
            if (current) sections.push(current);
            current = { label: m[1], file: m[2], lines: [] };
            continue;
        }
        if (!current) {
            current = { label: 'logs', file: 'combined', lines: [] };
        }
        current.lines.push(line);
    }
    if (current) sections.push(current);
    return sections.filter(section => section.lines.length > 0);
}

function parseTimestamp(ts) {
    if (!ts) return new Date(NaN);
    if (ts.includes(',')) {
        return new Date(ts.replace(' ', 'T').replace(',', '.'));
    }
    return new Date(ts);
}

function formatDate(ts) {
    const d = parseTimestamp(ts);
    return isNaN(d.getTime()) ? ts : d.toLocaleString();
}

function relativeTime(ts) {
    const d = parseTimestamp(ts);
    if (isNaN(d.getTime())) return '';
    const diff = Date.now() - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins} min ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs} hr${hrs === 1 ? '' : 's'} ago`;
    const days = Math.floor(hrs / 24);
    return `${days} day${days === 1 ? '' : 's'} ago`;
}

function formatWithRelative(ts) {
    if (!ts) return 'Waiting for data…';
    const rel = relativeTime(ts);
    return rel ? `${formatDate(ts)} (${rel})` : formatDate(ts);
}

function pickLatestTimestamp(timestamps) {
    const dated = timestamps
        .filter(Boolean)
        .map(ts => ({ ts, time: parseTimestamp(ts).getTime() }))
        .filter(entry => !isNaN(entry.time));
    if (!dated.length) return null;
    dated.sort((a, b) => b.time - a.time);
    return dated[0].ts;
}

function formatDateOnly(dateStr) {
    if (!dateStr) return '';
    const parts = dateStr.split('-').map(Number);
    if (parts.length !== 3 || parts.some(n => Number.isNaN(n))) return dateStr;
    const d = new Date(parts[0], parts[1] - 1, parts[2]);
    return isNaN(d.getTime()) ? dateStr : d.toLocaleDateString();
}

function formatTimeOnly(ts) {
    const d = parseTimestamp(ts);
    if (isNaN(d.getTime())) return ts || '';
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatBoilerInterval(interval) {
    const startTs = interval?.start || null;
    if (!startTs) return '';

    const start = formatTimeOnly(startTs);
    const endTs = interval?.end || null;
    const end = endTs ? formatTimeOnly(endTs) : 'now';

    const startDate = parseTimestamp(startTs);
    const endDate = endTs ? parseTimestamp(endTs) : new Date();
    let durationText = '';
    if (!isNaN(startDate.getTime()) && !isNaN(endDate.getTime())) {
        const mins = Math.max(0, Math.round((endDate.getTime() - startDate.getTime()) / 60000));
        const hours = Math.floor(mins / 60);
        const remMins = mins % 60;
        if (hours > 0 && remMins > 0) durationText = `${hours}h ${remMins}m`;
        else if (hours > 0) durationText = `${hours}h`;
        else durationText = `${remMins}m`;
    }

    return durationText ? `${start}-${end} (${durationText})` : `${start}-${end}`;
}

function normalizeRefreshMs(value, fallback) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(250, Math.min(60000, Math.round(parsed)));
}

function normalizeOnOff(value) {
    if (value === true) return 'ON';
    if (value === false) return 'OFF';
    if (typeof value === 'string') return value.toUpperCase();
    return null;
}

function buildPowerSummary(data) {
    const summary = data?.power_summary || {};
    const bluetti = data?.bluetti || {};

    return {
        acOutputOn: summary.acOutputOn ?? normalizeOnOff(bluetti.ac_output_on),
        acOutputTs: summary.acOutputTs ?? data?.generated_at ?? null,
        batteryPercent: summary.batteryPercent ?? bluetti.total_battery_percent ?? null,
        batteryTs: summary.batteryTs ?? data?.generated_at ?? null,
        pack2Battery: summary.pack2Battery ?? bluetti.pack_details2_percent ?? null,
        pack2Voltage: summary.pack2Voltage ?? bluetti.pack_details2_voltage ?? null,
        pack3Battery: summary.pack3Battery ?? bluetti.pack_details3_percent ?? null,
        pack3Voltage: summary.pack3Voltage ?? bluetti.pack_details3_voltage ?? null,
        dcInputPower: summary.dcInputPower ?? bluetti.dc_input_power ?? null,
        dcInputTs: summary.dcInputTs ?? data?.generated_at ?? null,
        acInputPower: summary.acInputPower ?? bluetti.ac_input_power ?? null,
        acInputTs: summary.acInputTs ?? data?.generated_at ?? null,
        acOutputPower: summary.acOutputPower ?? bluetti.ac_output_power ?? null,
        acOutputPowerTs: summary.acOutputPowerTs ?? data?.generated_at ?? null,
        lastMessageTs: summary.lastMessageTs ?? data?.connection?.last_message_ts ?? null,
        forcedOfflineTs: summary.forcedOfflineTs ?? null,
        forcedAcOffTs: summary.forcedAcOffTs ?? null
    };
}

function renderPowerSummary(summary) {
    const acVal = normalizeOnOff(summary.acOutputOn);
    acStatus.textContent = acVal ?? '—';
    acStatus.classList.toggle('on', acVal === 'ON');
    acStatus.classList.toggle('off', acVal === 'OFF');

    const acPower = summary.acOutputPower;
    const acPowerTs = summary.acOutputPowerTs || summary.acOutputTs;
    if (typeof acPower === 'number' && !isNaN(acPower)) {
        const tsText = acPowerTs ? formatWithRelative(acPowerTs) : '';
        acOutputDetail.textContent = `${Math.round(acPower)} W${tsText ? ' — ' + tsText : ''}`;
    } else {
        acOutputDetail.textContent = 'Waiting for power…';
    }

    const pct = summary.batteryPercent;
    batteryPercentEl.textContent = typeof pct === 'number' && !isNaN(pct) ? Math.round(pct) : '—';
    batteryTime.textContent = formatWithRelative(summary.batteryTs);

    const pack2 = summary.pack2Battery;
    const pack2Voltage = summary.pack2Voltage;
    const pack3 = summary.pack3Battery;
    const pack3Voltage = summary.pack3Voltage;
    const pack2Connected =
        (typeof pack2 === 'number' && !isNaN(pack2) && pack2 > 0) &&
        (typeof pack2Voltage !== 'number' || isNaN(pack2Voltage) || pack2Voltage > 1);
    const pack3Connected =
        (typeof pack3 === 'number' && !isNaN(pack3) && pack3 > 0) &&
        (typeof pack3Voltage !== 'number' || isNaN(pack3Voltage) || pack3Voltage > 1);
    const hasExtraPacks =
        pack2Connected || pack3Connected;
    batteryExtra.classList.toggle('hidden', !hasExtraPacks);

    const dc = summary.dcInputPower;
    const ac = summary.acInputPower;
    const inputOn = (dc ?? 0) > 0 || (ac ?? 0) > 0;
    inputStatus.textContent = inputOn ? 'ON' : 'OFF';
    inputStatus.classList.toggle('on', inputOn);
    inputStatus.classList.toggle('off', !inputOn);

    const parts = [];
    if (typeof dc === 'number' && !isNaN(dc)) parts.push(`DC ${Math.round(dc)} W`);
    if (typeof ac === 'number' && !isNaN(ac)) parts.push(`AC ${Math.round(ac)} W`);
    const latestInputTs = pickLatestTimestamp([summary.dcInputTs, summary.acInputTs]);
    const inputTsText = latestInputTs ? formatWithRelative(latestInputTs) : 'Waiting for data…';
    inputDetail.textContent = parts.length ? `${parts.join(' • ')} — ${inputTsText}` : inputTsText;

    const lastMsg = summary.lastMessageTs;
    const forcedOfflineTs = summary.forcedOfflineTs;
    const lastActivityTs = pickLatestTimestamp([lastMsg, forcedOfflineTs]);

    if (lastActivityTs) {
        const onlineByTraffic = lastMsg && (Date.now() - parseTimestamp(lastMsg).getTime()) < (connectionWindowMin * 60_000);
        const forcedOfflineRecent = forcedOfflineTs && forcedOfflineTs === lastActivityTs;
        const online = onlineByTraffic && !forcedOfflineRecent;

        connStatus.textContent = online ? 'ONLINE' : 'OFFLINE';
        connStatus.classList.toggle('on', online);
        connStatus.classList.toggle('off', !online);

        if (forcedOfflineRecent) {
            connDetail.textContent = `Last activity ${formatWithRelative(lastActivityTs)} (broker stopped)`;
        } else if (lastMsg) {
            connDetail.textContent = `Last message ${formatWithRelative(lastMsg)} (window ${connectionWindowMin}m)`;
        } else {
            connDetail.textContent = `Last activity ${formatWithRelative(lastActivityTs)}`;
        }
    } else {
        connStatus.textContent = '—';
        connDetail.textContent = 'Waiting for data…';
    }
}

function renderBoilerCard(boiler) {
    if (!boilerCard || !boilerCardValue || !boilerCardMeta) return;

    if (!boiler) {
        boilerCardValue.textContent = 'Unavailable';
        boilerCardMeta.textContent = 'No boiler data in system status';
        boilerCardMeta2.textContent = '';
        boilerCard.className = 'status-card boiler-card';
        return;
    }

    const completed = Boolean(boiler.completed);
    const isRunning = String(boiler.last_state || '').toLowerCase() === 'running';
    const intervals = Array.isArray(boiler.on_intervals) ? boiler.on_intervals : [];
    const intervalText = intervals
        .map(formatBoilerInterval)
        .filter(Boolean)
        .join(' • ');
    const dateLabel = boiler.date ? formatDateOnly(boiler.date) : 'today';

    const mainText = completed ? 'COMPLETE' : (isRunning ? 'RUNNING' : 'INCOMPLETE');
    const meta1 = dateLabel;
    const meta2 = intervalText ? `was running during: ${intervalText}` : 'was running during: —';

    boilerCardValue.textContent = mainText;
    boilerCardValue.className = `value ${completed ? 'on' : (isRunning ? 'warn' : 'off')}`;
    boilerCardMeta.textContent = meta1;
    boilerCardMeta2.textContent = meta2;
    boilerCard.className = `status-card boiler-card ${completed ? 'ok' : (isRunning ? 'running' : '')}`;
}

function renderChargingState(chargingState) {
    if (!chargingStateValue || !chargingStateMeta) return;
    if (!chargingState || !chargingState.current_state) {
        chargingStateValue.textContent = '—';
        chargingStateMeta.textContent = 'Waiting for state…';
        return;
    }

    chargingStateValue.textContent = chargingState.current_state;
    const transition = chargingState.last_transition;
    if (transition?.from && transition?.to) {
        const reason = transition.reason ? ` (${transition.reason})` : '';
        chargingStateMeta.textContent = `${transition.from} -> ${transition.to}${reason} • ${formatWithRelative(chargingState.updated_at || transition.timestamp)}`;
        return;
    }
    chargingStateMeta.textContent = `Updated ${formatWithRelative(chargingState.updated_at)}`;
}

async function fetchStatus() {
    try {
        const response = await fetch('/api/status', { cache: 'no-cache' });
        if (!response.ok) {
            return;
        }

        const data = await response.json();
        if (data?.connection?.window_min && Number.isFinite(Number(data.connection.window_min))) {
            connectionWindowMin = Number(data.connection.window_min);
        }
        applyRefreshConfig(data?.connection || {});

        renderPowerSummary(buildPowerSummary(data));
        renderBoilerCard(data?.boiler || null);
        renderChargingState(data?.charging_state || null);
    } catch (error) {
        console.error('Error fetching status:', error);
    }
}

function cancelLogsFetch() {
    // Leaving a log tab should immediately cancel any pending fetch.
    if (logFetchController) {
        logFetchController.abort();
        logFetchController = null;
    }
    logFetchInFlight = false;
}

function isLogView(view) {
    return Object.prototype.hasOwnProperty.call(LOG_VIEW_TO_SOURCE, view);
}

async function fetchLogsForView(view, force = false) {
    const source = LOG_VIEW_TO_SOURCE[view];
    if (!source) return;
    const state = getLogState(source);

    if (logFetchInFlight) {
        if (!force) return;
        cancelLogsFetch();
    }

    const controller = new AbortController();
    logFetchController = controller;
    logFetchInFlight = true;
    const incremental = !force && Boolean(state?.initialized && state?.latestTs);
    if (!incremental) {
        renderLogTextMessage('Loading logs...');
    }

    try {
        const response = await fetch(buildLogsUrl(source, { since: incremental ? state.latestTs : null }), {
            cache: 'no-cache',
            signal: controller.signal
        });

        const payload = await response.json().catch(() => null);
        if (!response.ok || !payload?.ok) {
            const errorMsg = payload?.error?.message || `Failed to fetch logs (${response.status})`;
            renderLogTextMessage(errorMsg);
            return;
        }

        if (Array.isArray(payload.sources) && payload.sources.length) {
            const selected = payload.sources.find(item => item?.label === source) || payload.sources[0];
            const nextState = updateLogStateFromSource(source, selected, incremental ? 'append' : 'replace');
            if (nextState) {
                renderLogState(source);
                return;
            }
            renderSingleLogSource(selected);
            return;
        }

        if (typeof payload.logs === 'string' && payload.logs.trim()) {
            const parsed = parseLegacyCombinedLogs(payload.logs);
            if (parsed.length) {
                const selected = parsed.find(item => item?.label === source) || parsed[0];
                if (selected) {
                    selected.lines = [...selected.lines].reverse();
                }
                renderSingleLogSource(selected);
            } else {
                renderLogTextMessage(payload.logs.split('\n').reverse().join('\n'));
            }
            return;
        }

        renderLogTextMessage('No logs available.');
    } catch (error) {
        if (error.name === 'AbortError') return;
        console.error('Error fetching logs:', error);
        renderLogTextMessage('Error fetching logs.');
    } finally {
        if (logFetchController === controller) {
            logFetchController = null;
            logFetchInFlight = false;
        }
    }
}

function positionTopbar(normalizedView, isDesktop) {
    if (!topbar || !statusView || !logView) return;

    // On mobile status view, place tabs above the status cards.
    if (!isDesktop && normalizedView === 'status') {
        if (document.body.firstElementChild !== topbar) {
            document.body.insertBefore(topbar, statusView);
        }
        return;
    }

    // Otherwise keep tabs between status panel and logs panel.
    if (statusView.nextElementSibling !== topbar) {
        document.body.insertBefore(topbar, logView);
    }
}

function ensureLogAutoRefresh() {
    if (logRefreshTimer) {
        clearInterval(logRefreshTimer);
    }
    logRefreshTimer = setInterval(() => {
        if (!isLogView(currentView)) return;
        fetchLogsForView(currentView, false);
    }, logRefreshMs);
}

function ensureStatusAutoRefresh() {
    if (statusRefreshTimer) {
        clearInterval(statusRefreshTimer);
    }
    statusRefreshTimer = setInterval(fetchStatus, statusRefreshMs);
}

function applyRefreshConfig(connection) {
    const nextStatusMs = normalizeRefreshMs(connection?.status_refresh_ms, statusRefreshMs);
    const nextLogMs = normalizeRefreshMs(connection?.logs_refresh_ms, logRefreshMs);
    const statusChanged = nextStatusMs !== statusRefreshMs;
    const logsChanged = nextLogMs !== logRefreshMs;

    statusRefreshMs = nextStatusMs;
    logRefreshMs = nextLogMs;

    if (statusChanged) {
        ensureStatusAutoRefresh();
    }
    if (logsChanged) {
        ensureLogAutoRefresh();
    }
}

function setView(view) {
    const previousView = currentView;
    const isDesktop = isDesktopLayout();
    const normalizedView = isDesktop && view === 'status' ? 'charging-log' : view;
    currentView = normalizedView;
    positionTopbar(normalizedView, isDesktop);

    statusView.classList.toggle('hidden', !isDesktop && normalizedView !== 'status');
    logView.classList.toggle('hidden', !isLogView(normalizedView));
    if (statusViewBtn) {
        statusViewBtn.classList.toggle('hidden', isDesktop);
    }
    viewButtons.forEach(btn => btn.classList.toggle('active', btn.dataset.view === normalizedView));

    if (isLogView(normalizedView) && normalizedView !== previousView) {
        fetchLogsForView(normalizedView, false);
    }
    if (isLogView(previousView) && previousView !== normalizedView) {
        cancelLogsFetch();
    }
}

window.addEventListener('resize', () => {
    setView(currentView);
});

viewButtons.forEach(btn => {
    btn.addEventListener('click', () => setView(btn.dataset.view));
});

refreshLogsBtn.addEventListener('click', () => {
    fetchLogsForView(currentView, true);
});

setView(isDesktopLayout() ? 'charging-log' : 'status');
fetchStatus();
ensureStatusAutoRefresh();
ensureLogAutoRefresh();
