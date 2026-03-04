import React from 'react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { t } from '../utils/i18n';
import AlertBanner from '../components/AlertBanner';
import RangeAreaChart from '../components/RangeAreaChart';
import RootCausePanel from '../components/RootCausePanel';
import {
    RadialBarChart, RadialBar, PolarAngleAxis, ResponsiveContainer,
} from 'recharts';
import { Thermometer, Gauge, Zap, Activity } from 'lucide-react';
import ViolationBanner from '../components/ViolationBanner';
import { toFixedSafe, toNumberOr } from '../utils/number';

export default function DashboardView({ onNav }) {
    const latest = useTelemetryStore(s => s.latest);
    const history = useTelemetryStore(s => s.history);
    const alerts = useTelemetryStore(s => s.alerts);
    const currentMachine = useTelemetryStore(s => s.currentMachine);
    const partNumber = useTelemetryStore(s => s.partNumber);
    const partOptions = useTelemetryStore(s => s.partOptions);
    const setPartNumber = useTelemetryStore(s => s.setPartNumber);
    const controlRoom = useTelemetryStore(s => s.controlRoom);
    const controlRoomLoading = useTelemetryStore(s => s.controlRoomLoading);
    const loadControlRoom = useTelemetryStore(s => s.loadControlRoom);
    const lstmPreview = useTelemetryStore(s => s.lstmPreview);

    const [now, setNow] = React.useState(new Date());

    React.useEffect(() => {
        const timer = setInterval(() => setNow(new Date()), 1000);
        return () => clearInterval(timer);
    }, []);

    React.useEffect(() => {
        void loadControlRoom(currentMachine, partNumber);
        // Auto-refresh Control Room Forecast every 2 minutes (date/time dependent)
        const refreshInterval = setInterval(() => {
            void loadControlRoom(currentMachine, partNumber);
        }, 120_000);
        return () => clearInterval(refreshInterval);
    }, [currentMachine, partNumber]); // machine-driven + part-driven + time-driven refresh

    const prob = latest?.predictions?.scrap_probability ?? 0;
    const pct = +(prob * 100).toFixed(1);
    const level = prob >= 0.9 ? 'crit' : prob >= 0.65 ? 'warn' : 'ok';
    const levelColor = { ok: 'var(--status-ok)', warn: 'var(--status-warn)', crit: 'var(--status-crit)' }[level];

    const topAlert = alerts.find(a => !a.acked);
    const gaugeData = [{ name: 'Scrap', value: pct, fill: levelColor }];

    // Quick telemetry stats setup
    // Variables ordered by correlation with Scrap_counter (from CSV audit)
    const tele = latest?.telemetry ?? {};
    const stats = [
        { label: 'Cushion', key: 'cushion', icon: Gauge, unit: 'mm', priority: true },
        { label: 'Shot Size', key: 'shot_size', icon: Activity, unit: 'mm', priority: true },   // corr=0.9999 ★
        { label: 'Ejector Torque', key: 'ejector_torque', icon: Zap, unit: 'Nm', priority: true }, // corr=0.990 ★
        { label: 'Dosage Time', key: 'dosage_time', icon: Gauge, unit: 's', priority: true },
        { label: 'Switch Pos.', key: 'switch_position', icon: Activity, unit: 'mm', priority: true },
        { label: 'Inj. Pressure', key: 'injection_pressure', icon: Activity, unit: 'bar' },
        { label: 'Inj. Time', key: 'injection_time', icon: Zap, unit: 's' },
        { label: 'Temp Zone 8', key: 'temp_z8', icon: Thermometer, unit: '°C' },  // active zone (50-60°C)
    ];

    const paramLabelMap = Object.fromEntries(stats.map(({ key, label }) => [key, label]));
    const formatSensorLabel = (sensorKey) => {
        if (!sensorKey) return 'Unknown';
        if (paramLabelMap[sensorKey]) return paramLabelMap[sensorKey];
        const normalized = String(sensorKey)
            .replace(/^temp_z(\d+)$/i, 'temp_zone_$1')
            .replace(/_/g, ' ')
            .trim()
            .toLowerCase();
        return normalized.replace(/\b\w/g, (char) => char.toUpperCase());
    };

    const controlRoomForecast = (
        controlRoom?.one_hour_parameter_forecast
        && typeof controlRoom.one_hour_parameter_forecast === 'object'
    )
        ? controlRoom.one_hour_parameter_forecast
        : null;

    const oneHourForecastRows = controlRoomForecast
        ? Object.entries(controlRoomForecast)
            .map(([key, forecast]) => {
                if (!forecast || typeof forecast !== 'object') return null;
                return {
                    key,
                    label: formatSensorLabel(key),
                    now: tele?.[key]?.value,
                    predicted: forecast?.predicted_value,
                    deviationChange: forecast?.deviation_change,
                    predictedDeviation: forecast?.predicted_deviation,
                    willExceed: Boolean(forecast?.will_exceed_tolerance),
                    etaMin: forecast?.expected_threshold_cross_minutes,
                };
            })
            .filter(Boolean)
            .sort((a, b) => Number(b.willExceed) - Number(a.willExceed) || Math.abs(b.deviationChange || 0) - Math.abs(a.deviationChange || 0))
            .slice(0, 5)
        : Object.entries(tele)
            .map(([key, param]) => {
                const forecast = param?.forecast_1h;
                if (!forecast || typeof forecast !== 'object') return null;
                return {
                    key,
                    label: formatSensorLabel(key),
                    now: param?.value,
                    predicted: forecast?.predicted_value,
                    deviationChange: forecast?.deviation_change,
                    predictedDeviation: forecast?.predicted_deviation,
                    willExceed: Boolean(forecast?.will_exceed_tolerance),
                    etaMin: forecast?.expected_threshold_cross_minutes,
                };
            })
            .filter(Boolean)
            .sort((a, b) => Number(b.willExceed) - Number(a.willExceed) || Math.abs(b.deviationChange || 0) - Math.abs(a.deviationChange || 0))
            .slice(0, 5);

    const goNoGo = prob < 0.4 ? 'GO' : 'NO-GO';
    const goColor = prob < 0.4 ? 'var(--status-ok)' : 'var(--status-crit)';
    const goBg = prob < 0.4 ? 'var(--status-ok-dim)' : 'var(--status-crit-dim)';
    const rootCausesRaw = Array.isArray(controlRoom?.root_causes) ? controlRoom.root_causes : [];
    // Safety filter: hide degenerate "near_limit" causes from zero-width envelopes (min == max).
    const rootCauses = rootCausesRaw.filter((cause) => {
        const min = Number(cause?.min);
        const max = Number(cause?.max);
        const hasBounds = Number.isFinite(min) && Number.isFinite(max);
        const degenerate = hasBounds && Math.abs(max - min) <= 1e-9;
        return !(cause?.status === 'near_limit' && degenerate);
    });
    const futureSummary = controlRoom?.future_summary || null;
    const peakFutureRisk = Number(futureSummary?.peak_scrap_probability);
    const peakFutureRiskLabel = Number.isFinite(peakFutureRisk)
        ? (peakFutureRisk > 0 && peakFutureRisk < 0.001 ? '<0.1%' : `${(peakFutureRisk * 100).toFixed(1)}%`)
        : '0.0%';
    const shapForPanel = (controlRoom?.root_cause_attributions?.length > 0)
        ? controlRoom.root_cause_attributions
        : latest?.shap_attributions;
    const telemetryForPanel = controlRoom?.current_telemetry
        ? controlRoom.current_telemetry
        : latest?.telemetry;
    const panelProb = Number.isFinite(controlRoom?.current_risk?.adjusted_probability)
        ? Number(controlRoom.current_risk.adjusted_probability)
        : prob;
    const partFilterScope = controlRoom?.part_filter_scope || 'machine_only';
    const partFilterMatchedCycles = Number(controlRoom?.part_filter_matched_cycles || 0);
    const partFilterTotalCycles = Number(controlRoom?.part_filter_total_cycles || 0);
    const partFilterMessage = typeof controlRoom?.part_filter_message === 'string'
        ? controlRoom.part_filter_message
        : '';
    const partFilterCycleStart = controlRoom?.part_filter_cycle_start;
    const partFilterCycleEnd = controlRoom?.part_filter_cycle_end;
    const partInDateWindow = Boolean(controlRoom?.part_number_in_date_window);
    const controlRoomPartOptions = Array.isArray(controlRoom?.part_options)
        ? controlRoom.part_options.filter(Boolean)
        : [];
    const effectivePartOptions = controlRoomPartOptions.length > 0 ? controlRoomPartOptions : partOptions;
    const modelFamily = controlRoom?.model_family || latest?.predictions?.model_family || 'legacy';
    const segmentScope = controlRoom?.segment_scope || latest?.predictions?.segment_scope || 'global';
    const featureSpecHash = controlRoom?.feature_spec_hash || latest?.predictions?.feature_spec_hash || '';
    const lstmProb = Number(lstmPreview?.scrap_probability ?? controlRoom?.lstm_preview?.scrap_probability);
    const lstmRiskLevel = String(lstmPreview?.risk_level || controlRoom?.lstm_preview?.risk_level || 'UNAVAILABLE');
    const lstmProbLabel = Number.isFinite(lstmProb) ? `${(lstmProb * 100).toFixed(1)}%` : 'N/A';
    const partScopeBadge = partFilterScope === 'machine+part'
        ? 'Machine + Part'
        : 'Machine Fallback';

    // P1: Calculate violating parameters for the banner
    const violatingParams = stats.filter(({ key, label }) => {
        const p = tele[key];
        if (!p) return false;
        const isOk = (p.safe_min === null || p.value >= p.safe_min) && (p.safe_max === null || p.value <= p.safe_max);
        return !isOk;
    }).map(s => ({ key: s.key, label: s.label }));

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>

            {/* Active alert banner */}
            {topAlert && <AlertBanner alert={topAlert} onNav={onNav} />}

            {/* P1: Process Violation Banner */}
            <ViolationBanner violations={violatingParams} machineId={currentMachine} />

            {/* Top row */}
            <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: 'var(--space-5)' }}>

                {/* Scrap gauge + go/no-go */}
                <div className="card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 'var(--space-4)', padding: 'var(--space-6)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%', marginBottom: -10 }}>
                        <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                            AI Scrap Analysis
                        </div>
                        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)' }}>
                            {now.toLocaleDateString()} {now.toLocaleTimeString()}
                        </div>
                    </div>

                    <div style={{ width: 180, height: 180, position: 'relative' }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <RadialBarChart
                                cx="50%" cy="50%" innerRadius="70%" outerRadius="100%"
                                barSize={16} data={gaugeData}
                                startAngle={225} endAngle={-45}
                            >
                                <PolarAngleAxis type="number" domain={[0, 100]} angleAxisId={0} tick={false} />
                                <RadialBar
                                    background={{ fill: 'var(--bg-elevated)' }}
                                    dataKey="value" angleAxisId={0} cornerRadius={8}
                                />
                            </RadialBarChart>
                        </ResponsiveContainer>
                        <div style={{
                            position: 'absolute', inset: 0,
                            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'
                        }}>
                            <div style={{ fontSize: 42, fontWeight: 900, color: levelColor, lineHeight: 1, fontFamily: 'JetBrains Mono, monospace' }}>{pct}</div>
                            <div style={{ fontSize: 15, fontWeight: 800, color: levelColor }}>% RISK</div>
                        </div>
                    </div>

                    {/* GO / NO-GO Panel */}
                    <div style={{
                        width: '100%', padding: '16px 0', borderRadius: 'var(--radius-lg)',
                        background: goBg, border: `2px solid ${goColor}33`,
                        textAlign: 'center', boxShadow: `0 8px 20px -10px ${goColor}44`
                    }}>
                        <div style={{ fontSize: 32, fontWeight: 900, color: goColor, letterSpacing: 6, lineHeight: 1 }}>{goNoGo}</div>
                        <div style={{ fontSize: 11, fontWeight: 700, color: goColor, marginTop: 4, opacity: 0.8 }}>
                            {prob < 0.4 ? 'PROCESS STABLE' : 'INTERVENTION REQ.'}
                        </div>
                    </div>

                    <div style={{ width: '100%', height: 1, background: 'var(--border-subtle)', margin: '4px 0' }} />

                    {/* Mini Stats Grid */}
                    <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 10 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)' }}>Primary Risk</span>
                            <span className={`badge ${prob > 0.5 ? 'badge-crit' : prob > 0.25 ? 'badge-warn' : 'badge-ok'}`}>
                                {latest?.predictions?.primary_defect_risk || 'Normal'}
                            </span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)' }}>AI Confidence</span>
                            <span style={{ fontSize: 12, fontWeight: 800, fontFamily: 'JetBrains Mono, monospace', color: 'var(--text-primary)' }}>
                                {((latest?.predictions?.confidence || 0) * 100).toFixed(0)}%
                            </span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)' }}>Cycle ID</span>
                            <span style={{ fontSize: 12, fontWeight: 800, fontFamily: 'JetBrains Mono, monospace', color: 'var(--text-primary)' }}>
                                #{latest?.cycle_id || '---'}
                            </span>
                        </div>
                    </div>
                </div>

                {/* Telemetry overview */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 'var(--space-3)' }}>
                        {stats.map(({ label, key, icon, unit, priority }) => {
                            const param = tele[key];
                            if (!param) return null;
                            const useHistoricalBaseline = useTelemetryStore.getState().useHistoricalBaseline;
                            const hSet = param.setpoint;
                            const aSet = param.official_setpoint ?? hSet;
                            const curSet = useHistoricalBaseline ? hSet : aSet;

                            const tol = (param.safe_max !== null && hSet !== null) ? (param.safe_max - hSet) : 0;
                            const safe_min = useHistoricalBaseline ? param.safe_min : (curSet !== null ? curSet - tol : null);
                            const safe_max = useHistoricalBaseline ? param.safe_max : (curSet !== null ? curSet + tol : null);

                            const { value, velocity } = param;
                            const ok = (safe_min === null || value >= safe_min) && (safe_max === null || value <= safe_max);
                            const lvl = ok ? 'ok' : 'crit';
                            return (
                                <div key={key} className={`stat-card ${lvl} ${priority ? 'priority' : ''}`} style={{ padding: '16px 20px', minHeight: 110 }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                                        {React.createElement(icon, { size: 16, color: ok ? 'var(--status-ok)' : 'var(--status-crit)' })}
                                        <div className="stat-label">{label}</div>
                                        <div style={{ marginLeft: 'auto', fontSize: 8, fontWeight: 900, color: (Date.now() - new Date(latest?.timestamp).getTime()) > 30000 ? 'var(--status-crit)' : 'var(--status-ok)', letterSpacing: '0.05em' }}>
                                            {(Date.now() - new Date(latest?.timestamp).getTime()) > 30000 ? 'STALE' : 'LIVE'}
                                        </div>
                                    </div>
                                    <div className="stat-value" style={{ fontSize: 30, color: ok ? 'var(--text-primary)' : 'var(--status-crit)', display: 'flex', alignItems: 'baseline', gap: 6 }}>
                                        {value}<span className="stat-unit">{unit}</span>
                                        {velocity !== 0 && (
                                            <span style={{ fontSize: 10, color: Math.abs(velocity) > 0.1 ? 'var(--status-warn)' : 'var(--text-muted)', fontWeight: 700, fontFamily: 'JetBrains Mono' }}>
                                                {velocity > 0 ? '↑' : '↓'} {Math.abs(velocity).toFixed(3)}
                                            </span>
                                        )}
                                    </div>
                                    {safe_min !== null && safe_max !== null && (
                                        <div style={{ marginTop: 8 }}>
                                            <div className="progress-track" style={{ height: 4, background: 'rgba(0,0,0,0.05)' }}>
                                                <div
                                                    className={`progress-fill ${lvl}`}
                                                    style={{ width: `${Math.min(100, Math.max(0, ((value - safe_min) / (safe_max - safe_min)) * 100))}%` }}
                                                />
                                            </div>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
                                                <span style={{ fontSize: 9, fontWeight: 700, fontFamily: 'JetBrains Mono', color: 'var(--text-muted)' }}>MIN {safe_min}</span>
                                                <span style={{ fontSize: 9, fontWeight: 700, fontFamily: 'JetBrains Mono', color: 'var(--text-muted)' }}>MAX {safe_max}</span>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>

                    <div className="card">
                        <span className="card-title-large">Control Room Forecast</span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            {controlRoom?.generated_at && (
                                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                                    <span style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 600 }}>
                                        DATA UP TO: {partFilterCycleEnd ? new Date(partFilterCycleEnd).toLocaleString() : (history.length > 0 ? new Date(history[history.length - 1].timestamp).toLocaleString() : '---')}
                                    </span>
                                    <span style={{ fontSize: 9, color: 'var(--text-muted)', fontWeight: 500 }}>
                                        FORECAST GENERATED: {new Date(controlRoom.generated_at).toLocaleTimeString()} (32h / 4 Shifts)
                                    </span>
                                    {partFilterCycleStart && partFilterCycleEnd ? (
                                        <span style={{ fontSize: 9, color: 'var(--text-muted)', fontWeight: 500 }}>
                                            PART DATE RANGE: {new Date(partFilterCycleStart).toLocaleString()} to {new Date(partFilterCycleEnd).toLocaleString()}
                                        </span>
                                    ) : null}
                                </div>
                            )}
                            <span className="badge badge-neutral">{currentMachine}</span>
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 8, marginBottom: 10 }}>
                            {effectivePartOptions.length > 0 ? (
                                <select
                                    value={partNumber}
                                    onChange={(e) => {
                                        const nextPart = e.target.value;
                                        setPartNumber(nextPart);
                                        void loadControlRoom(currentMachine, nextPart);
                                    }}
                                    style={{
                                        height: 34,
                                        border: '1px solid var(--border-default)',
                                        borderRadius: 8,
                                        padding: '0 10px',
                                        background: 'var(--bg-elevated)',
                                        color: 'var(--text-primary)'
                                    }}
                                >
                                    {effectivePartOptions.map((pn) => (
                                        <option key={pn} value={pn}>{pn}</option>
                                    ))}
                                </select>
                            ) : (
                                <input
                                    value={partNumber}
                                    onChange={(e) => setPartNumber(e.target.value)}
                                    placeholder="Part Number"
                                    style={{
                                        height: 34,
                                        border: '1px solid var(--border-default)',
                                        borderRadius: 8,
                                        padding: '0 10px',
                                        background: 'var(--bg-elevated)',
                                        color: 'var(--text-primary)'
                                    }}
                                />
                            )}
                            <button
                                className="btn btn-ghost"
                                onClick={() => loadControlRoom(currentMachine, partNumber)}
                                disabled={controlRoomLoading}
                            >
                                {controlRoomLoading ? 'Loading...' : 'Refresh'}
                            </button>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
                            <span className={`badge ${partFilterScope === 'machine+part' ? 'badge-ok' : 'badge-warn'}`}>
                                Scope: {partScopeBadge}
                            </span>
                            <span className="badge badge-info">
                                Model: {modelFamily}
                            </span>
                            <span className="badge badge-neutral">
                                Segment: {segmentScope}
                            </span>
                            <span className={`badge ${lstmRiskLevel === 'VERY_HIGH' || lstmRiskLevel === 'HIGH' ? 'badge-crit' : lstmRiskLevel === 'ELEVATED' ? 'badge-warn' : 'badge-ok'}`}>
                                LSTM: {lstmProbLabel} ({lstmRiskLevel})
                            </span>
                            <span className="badge badge-neutral">
                                Cycles: {partFilterMatchedCycles}/{partFilterTotalCycles}
                            </span>
                            {!partInDateWindow && partNumber ? (
                                <span className="badge badge-warn">
                                    Selected part not active in current date window
                                </span>
                            ) : null}
                            {partFilterMessage ? (
                                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{partFilterMessage}</span>
                            ) : null}
                        </div>
                        {featureSpecHash ? (
                            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 10, fontFamily: 'JetBrains Mono, monospace' }}>
                                Feature Spec: {String(featureSpecHash).slice(0, 12)}...
                            </div>
                        ) : null}
                        {futureSummary ? (
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, marginBottom: 10 }}>
                                <div style={{ padding: '8px 10px', borderRadius: 8, background: 'var(--bg-elevated)', fontSize: 12 }}>
                                    Peak Future Risk: <strong style={{ color: 'var(--status-crit)' }}>{peakFutureRiskLabel}</strong>
                                </div>
                                <div style={{ padding: '8px 10px', borderRadius: 8, background: 'var(--bg-elevated)', fontSize: 12 }}>
                                    Predicted Scrap Events: <strong>{futureSummary.predicted_scrap_events}</strong>
                                </div>
                            </div>
                        ) : (
                            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }}>
                                No control-room summary available.
                            </div>
                        )}
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>Top Root Causes</div>
                            {rootCauses.length > 0 ? rootCauses.slice(0, 3).map((cause) => (
                                <div key={`${cause.sensor}-${cause.status}`} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '6px 8px', borderRadius: 8, background: 'var(--bg-elevated)' }}>
                                    <span style={{ color: 'var(--text-primary)', fontWeight: 700 }}>{formatSensorLabel(cause.sensor)}</span>
                                    <span style={{ color: cause.status === 'near_limit' ? 'var(--status-warn)' : 'var(--status-crit)', fontFamily: 'JetBrains Mono, monospace' }}>
                                        {cause.status}
                                    </span>
                                </div>
                            )) : (
                                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No active breaches.</div>
                            )}
                        </div>
                    </div>

                    <div className="card">
                        <div className="card-header">
                            <span className="card-title-large">Next 1 Hour Parameter Forecast</span>
                            <span className="badge badge-info">Deviation Projection</span>
                        </div>
                        {oneHourForecastRows.length > 0 ? (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                {oneHourForecastRows.map((row) => (
                                    <div
                                        key={row.key}
                                        style={{
                                            display: 'grid',
                                            gridTemplateColumns: '1.1fr auto auto auto',
                                            alignItems: 'center',
                                            gap: 10,
                                            fontSize: 12,
                                            padding: '8px 10px',
                                            borderRadius: 8,
                                            background: row.willExceed ? 'var(--status-crit-dim)' : 'var(--bg-elevated)'
                                        }}
                                    >
                                        <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{row.label}</div>
                                        <div style={{ fontFamily: 'JetBrains Mono, monospace', color: 'var(--text-secondary)' }}>
                                            {`${row.now} -> ${row.predicted}`}
                                        </div>
                                        <div style={{ fontFamily: 'JetBrains Mono, monospace', color: row.deviationChange > 0 ? 'var(--status-crit)' : 'var(--status-ok)' }}>
                                            Dev {toFixedSafe(toNumberOr(row.predictedDeviation, 0), 3, '0.000')} | dDev {toNumberOr(row.deviationChange, 0) > 0 ? '+' : ''}{toFixedSafe(toNumberOr(row.deviationChange, 0), 3, '0.000')}
                                        </div>
                                        <span className={`badge ${row.willExceed ? 'badge-crit' : 'badge-ok'}`}>
                                            {row.willExceed
                                                ? `Risk${typeof row.etaMin === 'number' ? ` ${row.etaMin.toFixed(1)}m` : ''}`
                                                : 'Stable'}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                                Forecast will appear once velocity trends are available.
                            </div>
                        )}
                    </div>

                    {/* Main Analytics Chart */}
                    <div className="card" style={{ flex: 1 }}>
                        <div className="card-header">
                            <div>
                                <span className="card-title-large">Process Boundary Analysis</span>
                                <div style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 600, marginTop: 2 }}>CUSHION VS DYNAMIC SAFETY ENVELOPES</div>
                            </div>
                            <div style={{ display: 'flex', gap: 6 }}>
                                <span className="badge badge-info shadow-sm">AI Monitoring</span>
                                <span className="badge badge-neutral shadow-sm">32H / 4 SHIFTS</span>
                            </div>
                        </div>
                        <div style={{ height: 260 }}>
                            <RangeAreaChart history={history} forecast={controlRoom?.future_timeline} param="cushion" windowSize={60} />
                        </div>
                    </div>
                </div>
            </div>

            {/* Bottom: Explainable AI and Trends */}
            <div style={{ display: 'grid', gridTemplateColumns: '400px 1fr', gap: 'var(--space-5)' }}>
                <div className="card">
                    <div className="card-header">
                        <span className="card-title-large">Root Cause Drivers</span>
                        <div className="badge badge-neutral">SHAP ATTRIBUTIONS</div>
                    </div>
                    <RootCausePanel
                        shap={shapForPanel}
                        telemetry={telemetryForPanel}
                        scrapProb={panelProb}
                    />
                </div>

                <div className="card">
                    <div className="card-header">
                        <span className="card-title-large">High-Frequency Telemetry Trends</span>
                        <div style={{ display: 'flex', gap: 6 }}>
                            <span className="badge badge-info">Injection Pressure</span>
                            <span className="badge badge-info">Switch Pressure</span>
                        </div>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
                        <div style={{ height: 160 }}>
                            <RangeAreaChart history={history} forecast={controlRoom?.future_timeline} param="injection_pressure" windowSize={60} />
                        </div>
                        <div style={{ height: 160 }}>
                            <RangeAreaChart history={history} forecast={controlRoom?.future_timeline} param="switch_pressure" windowSize={60} />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
