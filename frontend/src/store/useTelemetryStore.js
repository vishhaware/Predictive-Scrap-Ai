import { create } from 'zustand';

const API_BASE = '/api';
let bootstrapPromise = null;
let hasBootstrapped = false;
const REQUEST_TIMEOUT_MS = 15000;
const REQUEST_RETRIES = 3;
const REQUEST_RETRY_DELAY_MS = 1200;
const FALLBACK_MACHINES = [
    { id: 'M231-11', name: 'M231-11', oee: 0, scraps: 0, status: 'unknown', temp: 230, cycles: 0 },
    { id: 'M356-57', name: 'M356-57', oee: 0, scraps: 0, status: 'unknown', temp: 230, cycles: 0 },
    { id: 'M471-23', name: 'M471-23', oee: 0, scraps: 0, status: 'unknown', temp: 230, cycles: 0 },
    { id: 'M607-30', name: 'M607-30', oee: 0, scraps: 0, status: 'unknown', temp: 230, cycles: 0 },
    { id: 'M612-33', name: 'M612-33', oee: 0, scraps: 0, status: 'unknown', temp: 230, cycles: 0 },
];
const DEFAULT_PREDICTIONS = {
    scrap_probability: 0,
    confidence: 0.95,
    risk_level: 'NORMAL',
    primary_defect_risk: 'None',
    engine_version: 'LSTM-Hyper v6.0.0-PRO',
    model_name: 'LSTM-Hyper+Hybrid',
    model_version: '6.0.0-PRO',
    model_label: 'LSTM-Scrap-AI-Core + Hybrid',
    model_family: 'lstm_hybrid',
    segment_scope: 'global',
    feature_spec_hash: null,
    xai_summary: null,
};

function wait(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function fetchJson(
    url,
    {
        retries = REQUEST_RETRIES,
        timeoutMs = REQUEST_TIMEOUT_MS,
        method = 'GET',
        headers = {},
        body = undefined,
    } = {}
) {
    let lastError = null;

    for (let attempt = 0; attempt <= retries; attempt++) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), timeoutMs);

        try {
            const response = await fetch(url, {
                method,
                headers,
                body,
                signal: controller.signal,
                cache: 'no-store',
            });
            if (Object.prototype.hasOwnProperty.call(response, 'ok') && !response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            if (typeof response.json !== 'function') {
                throw new Error('Invalid JSON response');
            }
            return await response.json();
        } catch (error) {
            lastError = error;
            if (attempt < retries) {
                await wait(REQUEST_RETRY_DELAY_MS * (attempt + 1));
            }
        } finally {
            clearTimeout(timeout);
        }
    }

    throw lastError || new Error('Unknown fetch error');
}

// ─── Zustand Store ───────────────────────────────────────────────────────────
export const useTelemetryStore = create((set, get) => ({
    // ── State ──────────────────────────────────────────────────────────────────
    currentMachine: 'M231-11',
    history: [],
    latest: null,
    alerts: [],
    alertCount: 0,
    auditLog: [
        { id: 1, ts: '15:10:02', actor: 'AI', msg: 'System initialized — loading real telemetry data' },
    ],
    replayIndex: 0,
    isReplaying: false,
    isLoading: true,
    machines: [],
    backendStatus: 'connecting', // connecting | online | degraded | offline
    backendInfo: null,
    partNumber: '',
    partOptions: [],
    controlRoom: null,
    controlRoomLoading: false,
    chartData: null,
    chartDataLoading: false,
    fleetChartData: null,
    fleetChartDataLoading: false,
    lstmPreview: null,
    lstmPreviewLoading: false,
    aiMetrics: null,
    aiMetricsLoading: false,
    lastMachinesRefreshAt: 0,
    lastCyclesRefreshAt: 0,
    lastControlRoomRefreshAt: 0,
    lastChartDataRefreshAt: 0,
    lastFleetChartDataRefreshAt: 0,
    lastAiMetricsRefreshAt: 0,
    useHistoricalBaseline: false,

    // ── Actions ────────────────────────────────────────────────────────────────
    setBackendStatus(status, backendInfo = null) {
        set((state) => ({
            backendStatus: status,
            backendInfo: backendInfo ?? (status === 'offline' ? null : state.backendInfo),
        }));
    },

    setUseHistoricalBaseline(val) {
        set({ useHistoricalBaseline: !!val });
    },

    async checkBackendHealth() {
        try {
            const health = await fetchJson(`${API_BASE}/health`, { retries: 1, timeoutMs: 5000 });
            const nextStatus = health?.ok ? 'online' : 'degraded';
            set({ backendStatus: nextStatus, backendInfo: health });
            return health;
        } catch {
            set({ backendStatus: 'offline', backendInfo: null });
            return null;
        }
    },

    async bootstrap() {
        if (hasBootstrapped) return;
        if (bootstrapPromise) return bootstrapPromise;

        bootstrapPromise = (async () => {
            set({ backendStatus: 'connecting' });
            await get().checkBackendHealth();
            await get().loadMachines();
            await get().loadMachineParts(get().currentMachine);
            await get().loadCycles(get().currentMachine);
            await get().loadControlRoom(get().currentMachine, get().partNumber);
            await get().loadChartData(get().currentMachine, get().partNumber, 60);
            await get().loadFleetChartData(60);
            await get().loadAiMetrics();
            hasBootstrapped = true;
        })().finally(() => {
            bootstrapPromise = null;
        });

        return bootstrapPromise;
    },

    // Load machines list from backend
    async loadMachines() {
        try {
            const machines = await fetchJson(`${API_BASE}/machines`);
            set({ machines, lastMachinesRefreshAt: Date.now() });
            get().setBackendStatus('online');
        } catch (err) {
            console.error('Failed to load machines:', err);
            get().setBackendStatus('degraded');
            set({ machines: FALLBACK_MACHINES, lastMachinesRefreshAt: Date.now() });
        }
    },

    // Load cycle history from backend for a specific machine
    async loadCycles(machineId) {
        set({ isLoading: true });
        try {
            const cycles = await fetchJson(`${API_BASE}/machines/${machineId}/cycles?limit=500`, {
                retries: 3,
                timeoutMs: 30000,
            });
            if (Array.isArray(cycles) && cycles.length > 0) {
                set({
                    history: cycles,
                    latest: cycles[cycles.length - 1],
                    replayIndex: cycles.length - 1,
                    isLoading: false,
                    lastCyclesRefreshAt: Date.now(),
                });
                if (cycles.length >= 10) {
                    void get().runLstmPreview({ machineId, maxSteps: 30, horizonMinutes: 60 });
                }
            } else {
                set({ history: [], latest: null, replayIndex: 0, isLoading: false, lastCyclesRefreshAt: Date.now() });
            }
            get().setBackendStatus('online');
        } catch (err) {
            console.error(`Failed to load cycles for ${machineId}:`, err);
            get().setBackendStatus('degraded');
            set({ history: [], latest: null, replayIndex: 0, isLoading: false, lastCyclesRefreshAt: Date.now() });
        }
    },

    setPartNumber(partNumber) {
        const normalized = typeof partNumber === 'string' ? partNumber.trim() : '';
        set({
            partNumber: normalized,
            controlRoom: null,
            controlRoomLoading: true,
            chartData: null,
            chartDataLoading: true,
        });
    },

    async loadMachineParts(machineId = get().currentMachine) {
        if (!machineId) return;
        try {
            const payload = await fetchJson(`${API_BASE}/machines/${machineId}/parts?limit=100`, {
                retries: 1,
                timeoutMs: 8000,
            });
            const parts = Array.isArray(payload?.parts)
                ? payload.parts.map((item) => item?.part_number).filter(Boolean)
                : [];
            const deduped = Array.from(new Set(parts));
            const state = get();
            const nextPart = deduped.includes(state.partNumber) ? state.partNumber : (deduped[0] || state.partNumber || '');
            set({ partOptions: deduped, partNumber: nextPart });
        } catch (err) {
            console.error(`Failed to load part catalog for ${machineId}:`, err);
            set({ partOptions: [] });
        }
    },

    async loadControlRoom(machineId = get().currentMachine, partNumber = get().partNumber) {
        if (!machineId) return;
        set({ controlRoomLoading: true });
        try {
            const query = new URLSearchParams({
                horizon_minutes: '60',
                history_window: '240',
                shift_hours: '24',  // date/time aware: only use last 24h of data
            });
            if (partNumber && String(partNumber).trim()) {
                query.set('part_number', String(partNumber).trim());
            }
            const payload = await fetchJson(`${API_BASE}/machines/${machineId}/control-room?${query.toString()}`, {
                retries: 2,
                timeoutMs: 30000,
            });
            set({
                controlRoom: payload,
                lstmPreview: payload?.lstm_preview || null,
                controlRoomLoading: false,
                lastControlRoomRefreshAt: Date.now(),
            });
            get().setBackendStatus('online');
        } catch (err) {
            console.error(`Failed to load control-room payload for ${machineId}:`, err);
            set({ controlRoomLoading: false });
            get().setBackendStatus('degraded');
        }
    },

    async loadChartData(
        machineId = get().currentMachine,
        partNumber = get().partNumber,
        horizonMinutes = 60,
    ) {
        if (!machineId) return;
        set({ chartDataLoading: true });
        try {
            const query = new URLSearchParams({
                horizon_minutes: String(Math.max(5, Math.min(Number(horizonMinutes) || 60, 1920))),
                history_limit: '500',
                shift_hours: '24',
            });
            if (partNumber && String(partNumber).trim()) {
                query.set('part_number', String(partNumber).trim());
            }
            const payload = await fetchJson(`${API_BASE}/machines/${machineId}/chart-data?${query.toString()}`, {
                retries: 2,
                timeoutMs: 30000,
            });
            set({
                chartData: payload,
                chartDataLoading: false,
                lastChartDataRefreshAt: Date.now(),
            });
            get().setBackendStatus('online');
        } catch (err) {
            console.error(`Failed to load chart-data payload for ${machineId}:`, err);
            set({ chartDataLoading: false });
            get().setBackendStatus('degraded');
        }
    },

    async loadFleetChartData(horizonMinutes = 60) {
        set({ fleetChartDataLoading: true });
        try {
            const query = new URLSearchParams({
                horizon_minutes: String(Math.max(5, Math.min(Number(horizonMinutes) || 60, 1920))),
                history_hours: '24',
                bucket_minutes: '5',
                shift_hours: '24',
            });
            const payload = await fetchJson(`${API_BASE}/fleet/chart-data?${query.toString()}`, {
                retries: 1,
                timeoutMs: 20000,
            });
            set({
                fleetChartData: payload,
                fleetChartDataLoading: false,
                lastFleetChartDataRefreshAt: Date.now(),
            });
            get().setBackendStatus('online');
        } catch (err) {
            console.error('Failed to load fleet chart-data:', err);
            set({ fleetChartDataLoading: false });
            get().setBackendStatus('degraded');
        }
    },

    async loadAiMetrics({
        machineId = '',
        windowCycles = 600,
        riskThreshold = 0.60,
        leadWindowCycles = 30,
    } = {}) {
        set({ aiMetricsLoading: true });
        try {
            const query = new URLSearchParams({
                window_cycles: String(Math.max(120, Math.min(Number(windowCycles) || 600, 5000))),
                risk_threshold: String(Math.max(0.05, Math.min(Number(riskThreshold) || 0.60, 0.95))),
                lead_window_cycles: String(Math.max(3, Math.min(Number(leadWindowCycles) || 30, 240))),
            });
            if (machineId && String(machineId).trim()) {
                query.set('machine_id', String(machineId).trim());
            }

            const payload = await fetchJson(`${API_BASE}/ai/metrics?${query.toString()}`, {
                retries: 1,
                timeoutMs: 12000,
            });
            set({
                aiMetrics: payload,
                aiMetricsLoading: false,
                lastAiMetricsRefreshAt: Date.now(),
            });
            get().setBackendStatus('online');
        } catch (err) {
            console.error('Failed to load AI metrics:', err);
            set({ aiMetricsLoading: false });
            get().setBackendStatus('degraded');
        }
    },

    async runLstmPreview({
        machineId = get().currentMachine,
        horizonMinutes = 60,
        maxSteps = 30,
    } = {}) {
        const { history } = get();
        const recent = Array.isArray(history) ? history.slice(-Math.max(10, maxSteps)) : [];
        if (recent.length < 10) return null;

        const sequence = recent
            .map((cycle) => cycle?.telemetry || {})
            .map((telemetry) => {
                const row = {};
                Object.entries(telemetry).forEach(([key, payload]) => {
                    const value = typeof payload === 'object' && payload !== null ? payload.value : payload;
                    const num = Number(value);
                    if (Number.isFinite(num)) row[key] = num;
                });
                return row;
            })
            .filter((row) => Object.keys(row).length > 0);

        if (sequence.length < 10) return null;
        set({ lstmPreviewLoading: true });
        try {
            const payload = await fetchJson(`${API_BASE}/ai/lstm/predict`, {
                retries: 0,
                timeoutMs: 10000,
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    machine_id: machineId,
                    sequence: sequence.slice(-Math.max(10, maxSteps)),
                    horizon_minutes: horizonMinutes,
                }),
            });
            set({ lstmPreview: payload, lstmPreviewLoading: false });
            return payload;
        } catch (err) {
            console.error('LSTM preview request failed:', err);
            set({ lstmPreviewLoading: false });
            return null;
        }
    },

    pushCycle(cycle) {
        if (!cycle || typeof cycle !== 'object') return;

        const safeCycle = {
            ...cycle,
            predictions: {
                ...DEFAULT_PREDICTIONS,
                ...(cycle.predictions || {}),
            },
            shap_attributions: Array.isArray(cycle.shap_attributions) ? cycle.shap_attributions : [],
        };

        const { history, alerts } = get();
        const last = history[history.length - 1];
        const lastKey = last ? `${last.cycle_id}|${last.timestamp}` : null;
        const nextKey = `${safeCycle.cycle_id}|${safeCycle.timestamp}`;
        const dedupedHistory = lastKey === nextKey ? history : [...history.slice(-499), safeCycle];

        const parsedProb = Number(safeCycle.predictions.scrap_probability);
        const prob = Number.isFinite(parsedProb) ? Math.max(0, Math.min(parsedProb, 1)) : 0;
        let newAlerts = [...alerts];

        if (prob >= 0.9) {
            newAlerts = [{
                id: Date.now(),
                level: 'crit',
                title: `${get().currentMachine} — CRITICAL: ${(prob * 100).toFixed(0)}% Scrap Probability`,
                body: `${safeCycle.predictions.primary_defect_risk} risk detected. Risk level: ${safeCycle.predictions.risk_level}. Immediate action required.`,
                cycle: safeCycle.cycle_id,
                ts: new Date().toLocaleTimeString(),
                acked: false,
            }, ...newAlerts.slice(0, 9)];
        } else if (prob >= 0.65 && newAlerts[0]?.level !== 'crit') {
            newAlerts = [{
                id: Date.now(),
                level: 'warn',
                title: `${get().currentMachine} — WARNING: ${(prob * 100).toFixed(0)}% Scrap Probability`,
                body: `Statistical drift detected. Risk level: ${safeCycle.predictions.risk_level}. Monitor closely.`,
                cycle: safeCycle.cycle_id,
                ts: new Date().toLocaleTimeString(),
                acked: false,
            }, ...newAlerts.slice(0, 9)];
        }

        set({
            history: dedupedHistory,
            latest: safeCycle,
            alerts: newAlerts,
            alertCount: newAlerts.filter(a => !a.acked).length,
            backendStatus: 'online',
            lastCyclesRefreshAt: Date.now(),
        });
    },

    ackAlert(id) {
        const { alerts, auditLog } = get();
        const updated = alerts.map(a => a.id === id ? { ...a, acked: true } : a);
        const alert = alerts.find(a => a.id === id);
        set({
            alerts: updated,
            alertCount: updated.filter(a => !a.acked).length,
            auditLog: [
                { id: Date.now(), ts: new Date().toLocaleTimeString(), actor: 'OPR-??', msg: `Acknowledged: ${alert?.title}` },
                ...auditLog,
            ],
        });
    },

    dismissAlert(id) {
        const { alerts } = get();
        set({
            alerts: alerts.filter(a => a.id !== id),
            alertCount: alerts.filter(a => !a.acked && a.id !== id).length,
        });
    },

    setHistory(history) {
        set({
            history,
            latest: history[history.length - 1],
            replayIndex: history.length - 1
        });
    },

    setReplayIndex(idx) {
        const { history } = get();
        const clamped = Math.max(0, Math.min(idx, history.length - 1));
        set({ replayIndex: clamped, latest: history[clamped] });
    },

    async switchMachine(machineId) {
        if (!machineId || machineId === get().currentMachine) return;
        set({
            currentMachine: machineId,
            history: [],
            latest: null,
            replayIndex: 0,
            isLoading: true,
            controlRoom: null,
            chartData: null,
            fleetChartData: null,
            lstmPreview: null,
            partOptions: [],
            partNumber: '',
        });
        try {
            // Load cycles first — this is the critical path for showing the UI
            await get().loadCycles(machineId);
        } catch (err) {
            console.error(`switchMachine: failed to load cycles for ${machineId}:`, err);
            set({ isLoading: false });
        }
        // Load auxiliary data in parallel (non-blocking)
        get().loadMachineParts(machineId).then(() => {
            get().loadControlRoom(machineId, get().partNumber);
            get().loadChartData(machineId, get().partNumber, 60);
        });
        get().loadFleetChartData(60);
        get().loadAiMetrics();
    },

    logAudit(entry) {
        const { auditLog } = get();
        set({ auditLog: [{ id: Date.now(), ts: new Date().toLocaleTimeString(), ...entry }, ...auditLog.slice(0, 49)] });
    },

    // ── Parameter Management ───────────────────────────────────────────────────────
    parameterConfigs: [],
    parameterLoading: false,
    parameterEditHistory: [],

    async loadParameters(machineId, parameterName) {
        set({ parameterLoading: true });
        try {
            const params = new URLSearchParams();
            if (machineId) params.append('machine_id', machineId);
            if (parameterName) params.append('parameter_name', parameterName);

            const data = await fetchJson(`${API_BASE}/admin/parameters?${params}`);
            set({ parameterConfigs: data, parameterLoading: false });
        } catch (error) {
            console.error('Failed to load parameters:', error);
            set({ parameterLoading: false });
        }
    },

    async saveParameter(parameterData) {
        try {
            const response = await fetch(`${API_BASE}/admin/parameters`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(parameterData),
            });
            if (!response.ok) throw new Error('Failed to save parameter');
            const result = await response.json();
            // Reload parameters after save
            await get().loadParameters(parameterData.machine_id);
            return result;
        } catch (error) {
            console.error('Failed to save parameter:', error);
            throw error;
        }
    },

    async revertParameterToCSV(parameterId) {
        try {
            const response = await fetch(`${API_BASE}/admin/parameters/${parameterId}/revert`, {
                method: 'POST',
            });
            if (!response.ok) throw new Error('Failed to revert parameter');
            // Reload parameters after revert
            await get().loadParameters();
            return true;
        } catch (error) {
            console.error('Failed to revert parameter:', error);
            throw error;
        }
    },

    async loadParameterHistory(parameterName, limit = 100) {
        try {
            const params = new URLSearchParams();
            if (parameterName) params.append('parameter_name', parameterName);
            params.append('limit', limit);

            const data = await fetchJson(`${API_BASE}/admin/parameter-history?${params}`);
            set({ parameterEditHistory: data });
        } catch (error) {
            console.error('Failed to load parameter history:', error);
        }
    },

    // ── Validation Rules ───────────────────────────────────────────────────────────
    validationRules: [],
    validationLoading: false,
    dataQualityViolations: [],

    async loadValidationRules(sensorName, machineId) {
        set({ validationLoading: true });
        try {
            const params = new URLSearchParams();
            if (sensorName) params.append('sensor_name', sensorName);
            if (machineId) params.append('machine_id', machineId);

            const data = await fetchJson(`${API_BASE}/admin/validation-rules?${params}`);
            set({ validationRules: data, validationLoading: false });
        } catch (error) {
            console.error('Failed to load validation rules:', error);
            set({ validationLoading: false });
        }
    },

    async createValidationRule(ruleData) {
        try {
            const response = await fetch(`${API_BASE}/admin/validation-rules`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(ruleData),
            });
            if (!response.ok) throw new Error('Failed to create validation rule');
            await get().loadValidationRules();
            return true;
        } catch (error) {
            console.error('Failed to create validation rule:', error);
            throw error;
        }
    },

    async deleteValidationRule(ruleId) {
        try {
            const response = await fetch(`${API_BASE}/admin/validation-rules/${ruleId}`, {
                method: 'DELETE',
            });
            if (!response.ok) throw new Error('Failed to delete validation rule');
            await get().loadValidationRules();
            return true;
        } catch (error) {
            console.error('Failed to delete validation rule:', error);
            throw error;
        }
    },

    async loadDataQualityViolations(machineId, hours = 24, severity) {
        try {
            const params = new URLSearchParams();
            params.append('hours', hours);
            if (severity) params.append('severity', severity);

            const data = await fetchJson(
                `${API_BASE}/machines/${machineId}/data-quality?${params}`
            );
            set({ dataQualityViolations: data.violations || [] });
        } catch (error) {
            console.error('Failed to load data quality violations:', error);
        }
    },

    // ── Model Metrics Actions ───────────────────────────────────────────────────────
    modelMetrics: {},
    metricsHistory: [],
    metricsLoading: false,
    modelComparison: {},

    async loadModelMetrics(modelId, machineId, hours = 24) {
        set({ metricsLoading: true });
        try {
            const params = new URLSearchParams();
            params.append('hours', hours);
            if (machineId) params.append('machine_id', machineId);

            const data = await fetchJson(`${API_BASE}/ai/model-metrics/${modelId}?${params}`);
            set({ modelMetrics: data.metrics || {}, metricsLoading: false });
        } catch (error) {
            console.error('Failed to load model metrics:', error);
            set({ metricsLoading: false });
        }
    },

    async loadMetricsHistory(modelId, machineId, hours = 168) {
        try {
            const params = new URLSearchParams();
            params.append('hours', hours);
            if (machineId) params.append('machine_id', machineId);

            const data = await fetchJson(`${API_BASE}/ai/metrics-history/${modelId}?${params}`);
            set({ metricsHistory: data.data || [] });
        } catch (error) {
            console.error('Failed to load metrics history:', error);
        }
    },

    async compareModels(modelIds, machineId) {
        try {
            const params = new URLSearchParams();
            params.append('model_ids', modelIds);
            if (machineId) params.append('machine_id', machineId);

            const data = await fetchJson(`${API_BASE}/ai/model-comparison?${params}`);
            set({ modelComparison: data.models || {} });
        } catch (error) {
            console.error('Failed to compare models:', error);
        }
    },

    async loadMetricsDashboard(hours = 24) {
        try {
            const params = new URLSearchParams();
            params.append('hours', hours);

            const data = await fetchJson(`${API_BASE}/ai/metrics-dashboard?${params}`);
            return data;
        } catch (error) {
            console.error('Failed to load metrics dashboard:', error);
            return null;
        }
    },

    async triggerMetricsComputation(machineId, windowHours = 24) {
        try {
            const params = new URLSearchParams();
            if (machineId) params.append('machine_id', machineId);
            params.append('window_hours', windowHours);

            const response = await fetch(`${API_BASE}/ai/compute-metrics?${params}`, {
                method: 'POST',
            });
            if (!response.ok) throw new Error('Failed to compute metrics');
            return await response.json();
        } catch (error) {
            console.error('Failed to trigger metrics computation:', error);
            throw error;
        }
    },
}));
