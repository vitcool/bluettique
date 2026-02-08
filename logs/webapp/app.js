const statusView = document.getElementById('statusView');
const logView = document.getElementById('logView');
const logSections = document.getElementById('logSections');
const logContent = document.getElementById('logContent');
const refreshLogsBtn = document.getElementById('refreshLogsBtn');
const viewButtons = document.querySelectorAll('.view-toggle button');

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

const STATUS_REFRESH_MS = 2000;
const DEFAULT_LOG_LIMIT = 800;
const urlParams = new URLSearchParams(window.location.search);
let connectionWindowMin = (() => {
    const val = Number(urlParams.get('conn_window_min'));
    if (Number.isFinite(val) && val > 0) return val;
    return 5;
})();

let currentView = 'status';
let logFetchController = null;
let logFetchInFlight = false;

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

function renderLogTextMessage(message) {
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
        appendLogSourceSection(label, file, lines);
    });
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

function formatSeconds(sec) {
    if (!Number.isFinite(sec) || sec < 0) return '';
    const totalMinutes = Math.round(sec / 60);
    const hours = Math.floor(totalMinutes / 60);
    const mins = totalMinutes % 60;
    return `${hours.toString().padStart(2, '0')}h ${mins.toString().padStart(2, '0')}m`;
}

function formatDateOnly(dateStr) {
    if (!dateStr) return '';
    const parts = dateStr.split('-').map(Number);
    if (parts.length !== 3 || parts.some(n => Number.isNaN(n))) return dateStr;
    const d = new Date(parts[0], parts[1] - 1, parts[2]);
    return isNaN(d.getTime()) ? dateStr : d.toLocaleDateString();
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
    const hasWindow = Boolean(boiler.window_start && boiler.window_end);
    const windowText = hasWindow ? `${boiler.window_start}-${boiler.window_end}` : '';
    const remainingText = formatSeconds(boiler.remaining_sec);
    const updated = boiler.last_update_ts ? formatWithRelative(boiler.last_update_ts) : 'n/a';
    const dateLabel = boiler.date ? formatDateOnly(boiler.date) : 'today';

    const mainText = completed ? 'COMPLETE' : 'INCOMPLETE';
    const meta1 = completed
        ? `${dateLabel} • Ran full window${windowText ? ` ${windowText}` : ''}`
        : `${dateLabel} • Remaining ${remainingText || 'unknown'}${windowText ? ` (${windowText})` : ''}`;

    boilerCardValue.textContent = mainText;
    boilerCardValue.className = `value ${completed ? 'on' : 'off'}`;
    boilerCardMeta.textContent = meta1;
    boilerCardMeta2.textContent = `Updated ${updated}`;
    boilerCard.className = `status-card boiler-card ${completed ? 'ok' : ''}`;
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

        renderPowerSummary(buildPowerSummary(data));
        renderBoilerCard(data?.boiler || null);
        renderChargingState(data?.charging_state || null);
    } catch (error) {
        console.error('Error fetching status:', error);
    }
}

function cancelLogsFetch() {
    // Leaving the Logs tab should immediately cancel any pending fetch.
    if (logFetchController) {
        logFetchController.abort();
        logFetchController = null;
    }
    logFetchInFlight = false;
}

async function fetchCombinedLogs(force = false) {
    if (logFetchInFlight) {
        if (!force) return;
        cancelLogsFetch();
    }

    const controller = new AbortController();
    logFetchController = controller;
    logFetchInFlight = true;
    renderLogTextMessage('Loading logs...');

    try {
        const response = await fetch(`/api/logs?limit=${DEFAULT_LOG_LIMIT}`, {
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
            renderLogSources(payload.sources);
            return;
        }

        if (typeof payload.logs === 'string' && payload.logs.trim()) {
            const parsed = parseLegacyCombinedLogs(payload.logs);
            if (parsed.length) {
                parsed.forEach(section => {
                    section.lines = [...section.lines].reverse();
                });
                renderLogSources(parsed);
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

function setView(view) {
    const previousView = currentView;
    currentView = view;
    const isDesktop = isDesktopLayout();

    statusView.classList.toggle('hidden', !isDesktop && view !== 'status');
    logView.classList.toggle('hidden', view !== 'log');
    viewButtons.forEach(btn => btn.classList.toggle('active', btn.dataset.view === view));

    if (view === 'log' && previousView !== 'log') {
        fetchCombinedLogs(false);
    }
    if (previousView === 'log' && view !== 'log') {
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
    fetchCombinedLogs(true);
});

setView('status');
fetchStatus();
setInterval(fetchStatus, STATUS_REFRESH_MS);
