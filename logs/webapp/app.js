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
const acStatus = document.getElementById('acStatus');
const acStatusTime = document.getElementById('acStatusTime');
const batteryPercentEl = document.getElementById('batteryPercent');
const batteryTime = document.getElementById('batteryTime');
const inputStatus = document.getElementById('inputStatus');
const inputDetail = document.getElementById('inputDetail');
const connStatus = document.getElementById('connStatus');
const connDetail = document.getElementById('connDetail');
const acOutputDetail = document.getElementById('acOutputDetail');
const LOG_LINE_LIMIT = 800; // cap full-log view for performance
const urlParams = new URLSearchParams(window.location.search);
const CONNECTION_WINDOW_MIN = (() => {
    const val = Number(urlParams.get('conn_window_min'));
    if (Number.isFinite(val) && val > 0) return val;
    return 5; // default freshness window in minutes
})();
const CONNECTION_WINDOW_MS = CONNECTION_WINDOW_MIN * 60_000;
const OFFLINE_WAIT_COOLDOWN_MIN = (() => {
    const val = Number(urlParams.get('offline_cooldown_min'));
    if (Number.isFinite(val) && val >= 0) return val;
    return 10; // default throttle window in minutes (was 360)
})();
const OFFLINE_WAIT_COOLDOWN_MS = OFFLINE_WAIT_COOLDOWN_MIN * 60_000;

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

function parseTimestamp(ts) {
    return new Date(ts.replace(' ', 'T').replace(',', '.'));
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

function formatDuration(ms) {
    if (!Number.isFinite(ms) || ms < 0) return '';
    const totalMinutes = Math.round(ms / 60000);
    const hours = Math.floor(totalMinutes / 60);
    const mins = totalMinutes % 60;
    return `${hours.toString().padStart(2, '0')}h ${mins.toString().padStart(2, '0')}m`;
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

function pickLatestTimestamp(timestamps) {
    const dated = timestamps
        .filter(Boolean)
        .map(ts => ({ ts, time: parseTimestamp(ts).getTime() }))
        .filter(entry => !isNaN(entry.time));
    if (!dated.length) return null;
    dated.sort((a, b) => b.time - a.time);
    return dated[0].ts;
}

function extractPowerSummary(lines) {
    const summary = {
        acOutputOn: null,
        acOutputTs: null,
        batteryPercent: null,
        batteryTs: null,
        dcInputPower: null,
        dcInputTs: null,
        acInputPower: null,
        acInputTs: null,
        acOutputPower: null,
        acOutputPowerTs: null,
        lastMessageTs: null,
        forcedOfflineTs: null,
        forcedAcOffTs: null
    };

    for (let i = lines.length - 1; i >= 0; i--) {
        const line = lines[i];
        const tsMatch = tsRegex.exec(line);
        const ts = tsMatch ? tsMatch[1] : null;

        if (!summary.lastMessageTs && ts && line.includes('Received message:')) {
            summary.lastMessageTs = ts;
        }

        if (summary.acOutputPower === null) {
            const match = line.match(/ac_output_power\s+(-?[\d.]+)/i);
            if (match) {
                summary.acOutputPower = parseFloat(match[1]);
                summary.acOutputPowerTs = ts;
            }
        }

        if (!summary.forcedAcOffTs && ts && line.includes('Bluetti: Turning AC device OFF')) {
            summary.acOutputOn = 'OFF';
            summary.acOutputTs = ts;
            summary.forcedAcOffTs = ts;
        }

        if (!summary.forcedOfflineTs && ts && line.includes('Bluetti: Stopping MQTT client and broker')) {
            summary.forcedOfflineTs = ts;
            if (!summary.forcedAcOffTs) {
                summary.acOutputOn = 'OFF';
                summary.acOutputTs = summary.acOutputTs || ts;
            }
        }

        if (summary.acOutputOn === null) {
            const match = line.match(/ac_output_on\s+(\w+)/i);
            if (match) {
                summary.acOutputOn = match[1].toUpperCase();
                summary.acOutputTs = ts;
            }
        }

        if (summary.batteryPercent === null) {
            const match = line.match(/total_battery_percent\s+([\d.]+)/i);
            if (match) {
                summary.batteryPercent = parseFloat(match[1]);
                summary.batteryTs = ts;
            }
        }

        if (summary.dcInputPower === null) {
            const match = line.match(/dc_input_power\s+(-?[\d.]+)/i);
            if (match) {
                summary.dcInputPower = parseFloat(match[1]);
                summary.dcInputTs = ts;
            }
        }

        if (summary.acInputPower === null) {
            const match = line.match(/ac_input_power\s+(-?[\d.]+)/i);
            if (match) {
                summary.acInputPower = parseFloat(match[1]);
                summary.acInputTs = ts;
            }
        }

        if (
            summary.acOutputOn !== null &&
            summary.batteryPercent !== null &&
            summary.dcInputPower !== null &&
            summary.acInputPower !== null &&
            summary.acOutputPower !== null
        ) {
            break;
        }
    }

    return summary;
}

function renderPowerSummary(summary) {
    const acVal = summary.acOutputOn;
    acStatus.textContent = acVal ?? '—';
    acStatus.classList.toggle('on', acVal === 'ON');
    acStatus.classList.toggle('off', acVal === 'OFF');
    acStatusTime.textContent = formatWithRelative(summary.acOutputTs);
    const acPower = summary.acOutputPower;
    const acPowerTs = summary.acOutputPowerTs || summary.acOutputTs;
    if (acOutputDetail) {
        if (typeof acPower === 'number' && !isNaN(acPower)) {
            const tsText = acPowerTs ? formatWithRelative(acPowerTs) : '';
            acOutputDetail.textContent = `${Math.round(acPower)} W${tsText ? ' — ' + tsText : ''}`;
        } else {
            acOutputDetail.textContent = 'Waiting for power…';
        }
    }

    const pct = summary.batteryPercent;
    batteryPercentEl.textContent = typeof pct === 'number' && !isNaN(pct) ? Math.round(pct) : '—';
    batteryTime.textContent = formatWithRelative(summary.batteryTs);

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
    const tsText = latestInputTs ? formatWithRelative(latestInputTs) : 'Waiting for data…';
    inputDetail.textContent = parts.length ? `${parts.join(' • ')} — ${tsText}` : tsText;

    const lastMsg = summary.lastMessageTs;
    const forcedOfflineTs = summary.forcedOfflineTs;
    const lastActivityTs = pickLatestTimestamp([lastMsg, forcedOfflineTs]);

    if (lastActivityTs) {
        const lastActivityAge = Date.now() - parseTimestamp(lastActivityTs).getTime();
        const onlineByTraffic = lastMsg && (Date.now() - parseTimestamp(lastMsg).getTime()) < CONNECTION_WINDOW_MS;
        const forcedOfflineRecent = forcedOfflineTs && forcedOfflineTs === lastActivityTs;
        const online = onlineByTraffic && !forcedOfflineRecent;

        connStatus.textContent = online ? 'ONLINE' : 'OFFLINE';
        connStatus.classList.toggle('on', online);
        connStatus.classList.toggle('off', !online);

        if (forcedOfflineRecent) {
            connDetail.textContent = `Last activity ${formatWithRelative(lastActivityTs)} (broker stopped)`;
        } else if (lastMsg) {
            connDetail.textContent = `Last message ${formatWithRelative(lastMsg)} (window ${CONNECTION_WINDOW_MIN}m)`;
        } else {
            connDetail.textContent = `Last activity ${formatWithRelative(lastActivityTs)}`;
        }
    } else {
        connStatus.textContent = '—';
        connDetail.textContent = 'Waiting for data…';
    }
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

        // Limit how much we render in the Full log tab to keep the UI responsive.
        const totalLines = lines.length;
        const logSlice = totalLines > LOG_LINE_LIMIT ? lines.slice(-LOG_LINE_LIMIT) : lines;
        const reversed = [...logSlice].reverse().join('\n');
        const notice = totalLines > LOG_LINE_LIMIT
            ? `(showing last ${LOG_LINE_LIMIT} of ${totalLines} lines)\n`
            : '';
        logContent.textContent = notice + reversed;

        const powerSummary = extractPowerSummary(lines);
        renderPowerSummary(powerSummary);

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
        let chargingStartTs = null;
        let offlineStartTs = null; // when electricity disappeared
        let lastElectricityBackTs = null; // when electricity came back
        let lastElectricityGoneTs = null; // when electricity disappeared
        let lastOfflineWaitTs = null; // throttle OFFLINE→WAIT entries
        let lastWaitOfflineTs = null; // throttle WAIT→OFFLINE entries
        let offlineSeriesActive = false; // suppress repeat WAIT->OFFLINE within the same outage
        for (let i = 0; i < entriesForView.length; i++) {
            const current = entriesForView[i];
            const prev = entriesForView[i - 1];
            if (!prev || current.state.trim() === prev.state.trim()) continue;
            const from = prev.state.trim();
            const to = current.state.trim();
            const nowTs = parseTimestamp(current.timestamp);
            const forceTransition =
                from.startsWith('Waiting 30.0s before first power check') && to === 'CHARGING';

            // Manage OFFLINE<->WAIT transitions: keep only the first WAIT->OFFLINE in a series; drop all OFFLINE->WAIT and further WAIT->OFFLINE until state leaves OFFLINE/WAIT.
            const pair = new Set([from, to]);
            const isOfflineWait = pair.has('WAIT') && pair.has('OFFLINE');
            if (!forceTransition && isOfflineWait) {
                if (from === 'WAIT' && to === 'OFFLINE') {
                    if (offlineSeriesActive) continue; // already recorded this outage
                    if (lastWaitOfflineTs) {
                        const deltaSinceLast = nowTs - parseTimestamp(lastWaitOfflineTs);
                        if (deltaSinceLast >= 0 && deltaSinceLast < OFFLINE_WAIT_COOLDOWN_MS) continue;
                    }
                    lastWaitOfflineTs = current.timestamp;
                    offlineSeriesActive = true; // mark series open
                } else if (from === 'OFFLINE' && to === 'WAIT') {
                    continue; // drop recoveries to reduce noise
                }
            }

            // Leaving OFFLINE/WAIT resets the series flag
            if (!pair.has('OFFLINE')) {
                offlineSeriesActive = false;
            }

            // Skip immediate duplicate transitions (same from->to) within 2 minutes
            if (!forceTransition) {
                const last = transitions[transitions.length - 1];
                if (last && last.from === from && last.to === to) {
                    const deltaMs = parseTimestamp(current.timestamp) - parseTimestamp(last.timestamp);
                    if (deltaMs >= 0 && deltaMs < 2 * 60 * 1000) continue;
                }
            }

            // Track starts for duration calculations
            if (to === 'CHARGING') {
                chargingStartTs = current.timestamp;
            }

            let detail = current.detail;

            // Custom descriptions
            if (from === 'Waiting 30.0s before first power check' && to === 'CHARGING') {
                detail = 'electricity back — starting charge';
            } else if (from === 'CHARGING' && to === 'WAIT') {
                if (chargingStartTs) {
                    const started = parseTimestamp(chargingStartTs);
                    const duration = nowTs - started;
                    const durText = formatDuration(duration);
                    detail = `finished charging${durText ? ` (time charging: ${durText})` : ''}`;
                } else {
                    detail = 'finished charging';
                }
                chargingStartTs = null;
            } else if (from === 'OFFLINE' && to === 'WAIT') {
                continue; // suppressed
            } else if (from === 'WAIT' && to === 'OFFLINE') {
                detail = 'electricity disappeared';
            }

            transitions.push({
                timestamp: current.timestamp,
                from,
                to,
                detail
            });
            prevTransitionTs = current.timestamp;
        }
        renderTransitions(transitions);
    } catch (error) {
        console.error('Error fetching logs:', error);
    }
}

setView('transitions');
setInterval(fetchLogs, 2000);
fetchLogs();
