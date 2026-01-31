const logContent = document.getElementById('logContent');
const stateTimeline = document.getElementById('stateTimeline');
const latestState = document.getElementById('latestState');
const latestTime = document.getElementById('latestTime');
const transitionsTimeline = document.getElementById('transitionsTimeline');
const transitionCount = document.getElementById('transitionCount');
const viewButtons = document.querySelectorAll('.view-toggle button');
const statesView = document.getElementById('statesView');
const transitionsView = document.getElementById('transitionsView');
const logView = document.getElementById('logView');

const stateRegex = /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - [A-Z]+ - Charging: ([^-]+?)(?: - (.*))?$/;
const tsRegex = /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})/;

function setView(view) {
    const showStates = view === 'states';
    const showTransitions = view === 'transitions';
    statesView.classList.toggle('hidden', !showStates);
    transitionsView.classList.toggle('hidden', !showTransitions);
    logView.classList.toggle('hidden', showStates || showTransitions);
    viewButtons.forEach(btn => btn.classList.toggle('active', btn.dataset.view === view));
}

viewButtons.forEach(btn => {
    btn.addEventListener('click', () => setView(btn.dataset.view));
});

function formatDate(ts) {
    const iso = ts.replace(' ', 'T').replace(',', '.');
    const d = new Date(iso);
    return isNaN(d.getTime()) ? ts : d.toLocaleString();
}

function relativeTime(ts) {
    const iso = ts.replace(' ', 'T').replace(',', '.');
    const d = new Date(iso);
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

function normalizeState(raw) {
    const trimmed = raw.trim();
    const upper = trimmed.toUpperCase();

    // Collapse noisy charging checks into a single CHARGING state
    if (
        upper.startsWith('POWER CHECK') ||
        upper.startsWith('STABLE CHECK') ||
        upper.startsWith('RECHECK') ||
        upper.startsWith('IN STARTUP GRACE') ||
        upper.startsWith('RECHECK -') ||
        upper.startsWith('RECHECK ') ||
        upper.startsWith('START_CHARGING') ||
        upper.startsWith('MONITORCHARGINGSTATE') // safety
    ) {
        return 'CHARGING';
    }

    // Charging start/stop
    if (upper.includes('START_CHARGING')) return 'CHARGING';
    if (upper.includes('STOP_CHARGING')) return 'WAIT';

    // Waiting / offline
    if (upper.includes('WAIT_POWER')) return 'WAIT';
    if (upper.startsWith('TAPO OFFLINE')) return 'OFFLINE';
    if (upper.startsWith('TAPO ONLINE')) return 'WAIT';

    // State transition lines -> map to target if present
    if (upper.startsWith('STATE TRANSITION')) {
        const match = trimmed.match(/->\\s*(\\w+)/);
        if (match) {
            const target = match[1].toUpperCase();
            if (target.includes('STARTCHARGING') || target.includes('MONITOR')) return 'CHARGING';
            if (target.includes('WAIT')) return 'WAIT';
            if (target.includes('STOP')) return 'WAIT';
        }
    }

    return trimmed;
}

function renderStateTimeline(entries) {
    if (!entries.length) {
        stateTimeline.innerHTML = '<div class="state-row"><div class="state-title">No Charging entries yet</div><div class="meta"></div><div class="detail">Waiting for the first state transition…</div></div>';
        latestState.textContent = '—';
        latestTime.textContent = 'Waiting for data…';
        return;
    }

    const latest = entries[entries.length - 1];
    latestState.textContent = latest.state.trim();
    const rel = relativeTime(latest.timestamp);
    latestTime.textContent = rel ? `${formatDate(latest.timestamp)} (${rel})` : formatDate(latest.timestamp);

    const recent = entries.slice().reverse(); // newest first
    stateTimeline.innerHTML = recent.map(item => {
        const friendly = formatDate(item.timestamp);
        const relTime = relativeTime(item.timestamp);
        const subtitle = relTime ? `${friendly} • ${relTime}` : friendly;
        const detail = item.detail ? `<div class="detail">${item.detail}</div>` : '';
        return `
            <div class="state-row">
                <div class="state-title">${item.state.trim()}</div>
                <div class="meta">${subtitle}</div>
                ${detail}
            </div>
        `;
    }).join('');
}

function renderTransitions(entries) {
    if (!entries.length) {
        transitionsTimeline.innerHTML = '<div class="state-row"><div class="state-title">No transitions yet</div><div class="meta"></div><div class="detail">Will show only when the state value changes</div></div>';
        transitionCount.textContent = '0';
        return;
    }

    transitionCount.textContent = `${entries.length} total`;
    const recent = entries.slice().reverse(); // newest first
    transitionsTimeline.innerHTML = recent.map(item => {
        const friendly = formatDate(item.timestamp);
        const relTime = relativeTime(item.timestamp);
        const subtitle = relTime ? `${friendly} • ${relTime}` : friendly;
        const detail = item.detail ? `<div class="detail">${item.detail}</div>` : '';
        return `
            <div class="state-row">
                <div class="state-title">${item.from} → ${item.to}</div>
                <div class="meta">${subtitle}</div>
                ${detail}
            </div>
        `;
    }).join('');
}

async function fetchLogs() {
    try {
        const response = await fetch('log.txt', { cache: 'no-cache' });
        if (!response.ok) {
            console.error(`Failed to fetch logs: ${response.status}`);
            return;
        }

        const text = await response.text();
        const lines = text.split('\n');
        const reversed = [...lines].reverse().join('\n');
        logContent.textContent = reversed;

        const stateEntries = [];
        for (const line of lines) {
            const match = stateRegex.exec(line);
            if (match) {
                const rawState = match[2];
                const normalized = normalizeState(rawState);
                const detail = match[3]?.trim() ?? '';
                stateEntries.push({
                    timestamp: match[1],
                    state: normalized,
                    detail: detail || (normalized !== rawState ? rawState : '')
                });
                continue;
            }

            // Capture app start lines (e.g., "Starting Bluetti DC cycle test...")
            if (line.includes('Starting Bluetti')) {
                const tsMatch = tsRegex.exec(line);
                const ts = tsMatch ? tsMatch[1] : null;
                if (ts) {
                    const afterInfo = line.split(' - INFO - ');
                    const detail = afterInfo.length > 1 ? afterInfo[1].trim() : 'App started';
                    stateEntries.push({
                        timestamp: ts,
                        state: 'APP_START',
                        detail
                    });
                }
            }
        }

        // Keep only the last 24h if possible; fallback to all
        const dayAgo = Date.now() - 24 * 60 * 60 * 1000;
        const withinDay = stateEntries.filter(e => {
            const d = new Date(e.timestamp.replace(' ', 'T').replace(',', '.'));
            return !isNaN(d) && d.getTime() >= dayAgo;
        });
        const entriesForView = withinDay.length ? withinDay : stateEntries;

        renderStateTimeline(entriesForView);
        const transitions = [];
        for (let i = 0; i < entriesForView.length; i++) {
            const current = entriesForView[i];
            const prev = entriesForView[i - 1];
            if (!prev || current.state.trim() === prev.state.trim()) continue;
            const from = prev.state.trim();
            const to = current.state.trim();

            // Skip noisy offline<->wait and wait<->charging bounces
            const pair = new Set([from, to]);
            const isOfflineWaitBounce = pair.has('WAIT') && pair.has('OFFLINE');
            const isWaitChargingBounce = pair.has('WAIT') && pair.has('CHARGING');
            if (isOfflineWaitBounce || isWaitChargingBounce) continue;

            transitions.push({
                timestamp: current.timestamp,
                from,
                to,
                detail: current.detail
            });
        }
        renderTransitions(transitions);
    } catch (error) {
        console.error('Error fetching logs:', error);
    }
}

setView('states');
setInterval(fetchLogs, 2000);
fetchLogs();
