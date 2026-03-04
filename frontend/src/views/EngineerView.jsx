import { useState, useMemo, useEffect } from 'react';
import { Activity, AlertTriangle, Download, ShieldCheck, Sparkles } from 'lucide-react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import RangeAreaChart from '../components/RangeAreaChart';
import RelationalScatterPlot from '../components/RelationalScatterPlot';
import RootCausePanel from '../components/RootCausePanel';
import ViolationBanner from '../components/ViolationBanner';

const PREFERRED_PARAMS = [
    'cushion',
    'shot_size',
    'ejector_torque',
    'injection_pressure',
    'switch_pressure',
    'temp_z8',
    'temp_z1',
    'temp_z3',
];

const STATUS_PRIORITY = { crit: 0, warn: 1, ok: 2, na: 3 };

function formatParamLabel(key) {
    return String(key || 'unknown')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (char) => char.toUpperCase());
}

function inferUnit(key, param) {
    if (typeof param?.unit === 'string' && param.unit.trim()) return param.unit.trim();
    if (key.includes('temp')) return '°C';
    if (key.includes('pressure')) return 'bar';
    if (key.includes('torque')) return 'Nm';
    if (key.includes('time')) return 's';
    if (key.includes('cushion') || key.includes('shot') || key.includes('switch')) return 'mm';
    return '';
}

function formatNum(value, digits = 2) {
    const num = Number(value);
    if (!Number.isFinite(num)) return '--';
    return num.toFixed(digits);
}

export default function EngineerView() {
    const history = useTelemetryStore(s => s.history);
    const latest = useTelemetryStore(s => s.latest);
    const currentMachine = useTelemetryStore(s => s.currentMachine);
    const partNumber = useTelemetryStore(s => s.partNumber);
    const controlRoom = useTelemetryStore(s => s.controlRoom);
    const chartData = useTelemetryStore(s => s.chartData);

    const [activeTab, setActiveTab] = useState('telemetry');
    const [isExporting, setIsExporting] = useState(false);

    useEffect(() => {
        if (!currentMachine) return;
        void useTelemetryStore.getState().loadControlRoom(currentMachine, partNumber);
    }, [currentMachine, partNumber]);

    const handleExport = async () => {
        setIsExporting(true);
        try {
            const resp = await fetch('/api/admin/export-validation', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            let payload = null;
            try {
                payload = await resp.json();
            } catch {
                payload = null;
            }

            const errorMessage =
                payload?.error ||
                payload?.detail ||
                payload?.message ||
                `HTTP ${resp.status}`;

            if (resp.ok && payload?.ok) {
                const artifacts = [
                    payload?.validation_workbook ? `Workbook: ${payload.validation_workbook}` : null,
                    payload?.live_check_csv ? `Live CSV: ${payload.live_check_csv}` : null,
                    payload?.backtest_csv ? `Backtest CSV: ${payload.backtest_csv}` : null,
                ].filter(Boolean);
                alert(`Success! Validation artifacts generated.\n${artifacts.join('\n')}`);
            } else {
                alert('Export failed: ' + errorMessage);
            }
        } catch (err) {
            alert('Export error: ' + err.message);
        } finally {
            setIsExporting(false);
        }
    };

    const telemetryParams = useMemo(() => {
        const latestTelemetry = latest?.telemetry || {};
        const available = Object.keys(latestTelemetry);
        const ordered = PREFERRED_PARAMS.filter((param) => available.includes(param));
        const fallback = available
            .filter((param) => !ordered.includes(param))
            .slice(0, 8 - ordered.length);
        return [...ordered, ...fallback].slice(0, 8);
    }, [latest]);

    const telemetryRows = useMemo(() => {
        const tele = latest?.telemetry || {};
        const rows = Object.entries(tele).map(([key, param]) => {
            const value = Number(param?.value);
            const setpoint = Number(param?.official_setpoint ?? param?.setpoint);
            const safeMinRaw = Number(param?.safe_min);
            const safeMaxRaw = Number(param?.safe_max);
            const safeMin = Number.isFinite(safeMinRaw) ? safeMinRaw : null;
            const safeMax = Number.isFinite(safeMaxRaw) ? safeMaxRaw : null;
            const velocityRaw = Number(param?.velocity);
            const velocity = Number.isFinite(velocityRaw) ? velocityRaw : null;

            const hasBounds = safeMin !== null && safeMax !== null && safeMax > safeMin;
            const outOfBounds = hasBounds && Number.isFinite(value) && (value < safeMin || value > safeMax);

            let nearLimit = false;
            if (hasBounds && Number.isFinite(value) && !outOfBounds) {
                const range = safeMax - safeMin;
                const safetyBand = range * 0.15;
                nearLimit = value <= safeMin + safetyBand || value >= safeMax - safetyBand;
            }

            const status = outOfBounds ? 'crit' : (nearLimit ? 'warn' : (Number.isFinite(value) ? 'ok' : 'na'));
            const deviation = Number.isFinite(value) && Number.isFinite(setpoint) ? value - setpoint : null;

            return {
                key,
                label: formatParamLabel(key),
                value: Number.isFinite(value) ? value : null,
                setpoint: Number.isFinite(setpoint) ? setpoint : null,
                safeMin,
                safeMax,
                deviation,
                velocity,
                unit: inferUnit(key, param),
                status,
            };
        });

        const preferredRank = new Map(telemetryParams.map((param, index) => [param, index]));
        return rows.sort((a, b) => {
            const statusDiff = (STATUS_PRIORITY[a.status] ?? 99) - (STATUS_PRIORITY[b.status] ?? 99);
            if (statusDiff !== 0) return statusDiff;

            const prefA = preferredRank.has(a.key) ? preferredRank.get(a.key) : 99;
            const prefB = preferredRank.has(b.key) ? preferredRank.get(b.key) : 99;
            if (prefA !== prefB) return prefA - prefB;

            return a.label.localeCompare(b.label);
        });
    }, [latest, telemetryParams]);

    const scrapProbability = Number(latest?.predictions?.scrap_probability ?? 0);
    const scrapRiskPct = Number.isFinite(scrapProbability) ? scrapProbability * 100 : 0;
    const criticalCount = telemetryRows.filter((row) => row.status === 'crit').length;
    const warningCount = telemetryRows.filter((row) => row.status === 'warn').length;
    const healthyCount = telemetryRows.filter((row) => row.status === 'ok').length;
    const modelLabel = latest?.predictions?.model_label || latest?.predictions?.engine_version || 'forecasted model';
    const lastUpdateLabel = latest?.timestamp ? new Date(latest.timestamp).toLocaleString() : 'N/A';
    const futureStartLabel = chartData?.meta?.future_first_ts
        ? new Date(chartData.meta.future_first_ts).toLocaleString()
        : 'N/A';

    const violations = useMemo(() => {
        const tele = latest?.telemetry || {};
        return Object.entries(tele)
            .filter(([, p]) => {
                const ok = (p.safe_min === null || p.value >= p.safe_min) && (p.safe_max === null || p.value <= p.safe_max);
                return !ok;
            })
            .map(([k]) => ({ key: k, label: k.replace(/_/g, ' ').toUpperCase() }));
    }, [latest]);

    return (
        <div className="engineer-view">

            <ViolationBanner violations={violations} machineId={currentMachine} />

            <div className="card engineer-hero">
                <div className="engineer-hero-main">
                    <div className="engineer-kicker">Engineer Console</div>
                    <h2 className="engineer-title">Process Intelligence Dashboard</h2>
                    <div className="engineer-subtitle">
                        Machine {currentMachine || 'N/A'} · Part {partNumber || 'AUTO'}
                    </div>
                    <div className="engineer-hero-tags">
                        <span className={`badge ${criticalCount > 0 ? 'badge-crit' : 'badge-ok'}`}>
                            {criticalCount > 0 ? `${criticalCount} critical parameters` : 'No critical parameters'}
                        </span>
                        <span className="badge badge-info">Model: {modelLabel}</span>
                        <span className="badge badge-neutral">Next forecast: {futureStartLabel}</span>
                    </div>
                </div>
                <div className="engineer-hero-actions">
                    <button
                        className="btn btn-primary"
                        onClick={handleExport}
                        disabled={isExporting}
                        style={{ gap: 8 }}
                    >
                        <Download size={14} /> {isExporting ? 'Processing...' : 'Export Excel Validation'}
                    </button>
                    <div className="engineer-hero-time">Last update: {lastUpdateLabel}</div>
                </div>
            </div>

            <div className="engineer-kpi-grid">
                <div className="engineer-kpi-card">
                    <div className="engineer-kpi-head">
                        <AlertTriangle size={14} />
                        Live Scrap Risk
                    </div>
                    <div className="engineer-kpi-value text-crit">{scrapRiskPct.toFixed(1)}%</div>
                    <div className="engineer-kpi-note">Current cycle probability</div>
                </div>
                <div className="engineer-kpi-card">
                    <div className="engineer-kpi-head">
                        <ShieldCheck size={14} />
                        Healthy Parameters
                    </div>
                    <div className="engineer-kpi-value text-ok">{healthyCount}</div>
                    <div className="engineer-kpi-note">Within safe operating limits</div>
                </div>
                <div className="engineer-kpi-card">
                    <div className="engineer-kpi-head">
                        <Sparkles size={14} />
                        Warning Parameters
                    </div>
                    <div className="engineer-kpi-value text-warn">{warningCount}</div>
                    <div className="engineer-kpi-note">Near tolerance boundaries</div>
                </div>
                <div className="engineer-kpi-card">
                    <div className="engineer-kpi-head">
                        <Activity size={14} />
                        Tracked Signals
                    </div>
                    <div className="engineer-kpi-value">{telemetryRows.length}</div>
                    <div className="engineer-kpi-note">Live parameter channels</div>
                </div>
            </div>

            <div className="engineer-toolbar">
                <div className="tabs">
                    {[
                        { id: 'telemetry', label: 'Multi-Param Telemetry' },
                        { id: 'relational', label: 'Relational Plot' },
                    ].map(tab => (
                        <button
                            key={tab.id}
                            className={`tab-btn${activeTab === tab.id ? ' active' : ''}`}
                            onClick={() => setActiveTab(tab.id)}
                        >
                            {tab.label}
                        </button>
                    ))}
                </div>
            </div>

            {chartData?.meta && (
                <div className="engineer-seam-note">
                    Past -&gt; Future seam — last observed: {chartData.meta.past_last_ts ? new Date(chartData.meta.past_last_ts).toLocaleString() : 'N/A'} · first forecast: {chartData.meta.future_first_ts ? new Date(chartData.meta.future_first_ts).toLocaleString() : 'N/A'}
                </div>
            )}
            {activeTab === 'telemetry' && (
                <div className="engineer-chart-grid">
                    {telemetryParams.map(param => (
                        <div key={param} className="card engineer-chart-card">
                            <RangeAreaChart history={history} forecast={controlRoom?.future_timeline} param={param} windowSize={80} />
                        </div>
                    ))}
                </div>
            )}

            {activeTab === 'relational' && (
                <div className="engineer-relational-grid">
                    <div className="card engineer-chart-card">
                        <div className="card-header">
                            <span className="card-title-large">Pressure Correlation View</span>
                        </div>
                        <RelationalScatterPlot history={history} windowSize={200} />
                    </div>
                    <div className="card engineer-chart-card">
                        <div className="card-header">
                            <span className="card-title-large">AI Root Cause — Latest Cycle</span>
                        </div>
                        <RootCausePanel
                            shap={latest?.shap_attributions}
                            telemetry={latest?.telemetry}
                            scrapProb={latest?.predictions?.scrap_probability ?? 0}
                        />
                    </div>
                </div>
            )}

            <div className="card engineer-params-card">
                <div className="card-header">
                    <span className="card-title-large">Parameter Monitor</span>
                    <span className="badge badge-neutral">{telemetryRows.length} parameters</span>
                </div>
                <div className="engineer-params-subtitle">
                    Bottom panel for quick parameter diagnostics across value, tolerance, and deviation.
                </div>
                {telemetryRows.length === 0 ? (
                    <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No telemetry parameters available.</div>
                ) : (
                    <div className="engineer-params-table-wrap">
                        <table className="engineer-params-table">
                            <thead>
                                <tr>
                                    <th>Parameter</th>
                                    <th>Value</th>
                                    <th>Setpoint</th>
                                    <th>Safe Range</th>
                                    <th>Deviation</th>
                                    <th>Trend</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                {telemetryRows.map((row) => (
                                    <tr key={row.key}>
                                        <td>
                                            <div className="engineer-param-name">{row.label}</div>
                                            <div className="engineer-param-key">{row.key}</div>
                                        </td>
                                        <td className="engineer-param-mono">
                                            {formatNum(row.value)} {row.unit}
                                        </td>
                                        <td className="engineer-param-mono">{formatNum(row.setpoint)}</td>
                                        <td className="engineer-param-mono">
                                            {row.safeMin !== null && row.safeMax !== null
                                                ? `${formatNum(row.safeMin)} - ${formatNum(row.safeMax)}`
                                                : 'N/A'}
                                        </td>
                                        <td className={`engineer-param-deviation ${row.deviation === null ? '' : (row.deviation >= 0 ? 'positive' : 'negative')}`}>
                                            {row.deviation === null ? 'N/A' : `${row.deviation >= 0 ? '+' : ''}${formatNum(row.deviation)}`}
                                        </td>
                                        <td className={`engineer-param-deviation ${row.velocity === null ? '' : (row.velocity >= 0 ? 'positive' : 'negative')}`}>
                                            {row.velocity === null ? 'N/A' : `${row.velocity >= 0 ? '↑' : '↓'} ${formatNum(Math.abs(row.velocity), 3)}`}
                                        </td>
                                        <td>
                                            <span className={`engineer-status-chip ${row.status}`}>
                                                {row.status === 'crit' ? 'Critical' : row.status === 'warn' ? 'Warning' : row.status === 'ok' ? 'Stable' : 'N/A'}
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    );
}
