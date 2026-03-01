import { useMemo } from 'react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { t } from '../utils/i18n';
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
    LineChart, Line, Legend,
} from 'recharts';
import { TrendingDown, TrendingUp, Award, AlertCircle } from 'lucide-react';

export default function ManagerView() {
    const machines = useTelemetryStore(s => s.machines);
    const history = useTelemetryStore(s => s.history);
    const aiMetrics = useTelemetryStore(s => s.aiMetrics);

    const fleetMetrics = aiMetrics?.fleet_metrics || null;
    const perMachineMetrics = Array.isArray(aiMetrics?.per_machine) ? aiMetrics.per_machine : [];
    const perMachineMetricMap = useMemo(() => (
        Object.fromEntries(
            perMachineMetrics
                .filter((item) => item && typeof item.machine_id === 'string')
                .map((item) => [item.machine_id, item])
        )
    ), [perMachineMetrics]);

    const overallOEE = machines.length > 0
        ? Math.round(machines.reduce((a, m) => a + m.oee, 0) / machines.length)
        : 0;
    const totalScraps = Number.isFinite(fleetMetrics?.observed_scrap_events)
        ? fleetMetrics.observed_scrap_events
        : machines.reduce((a, m) => a + m.scraps, 0);
    const liveCritMachines = machines.filter(m => m.status === 'crit').length;
    const liveWarnMachines = machines.filter(m => m.status === 'warn').length;
    const predictiveCritMachines = perMachineMetrics.filter((metric) => {
        const missedRate = Number(metric?.missed_scrap_rate);
        const recall = Number(metric?.recall);
        return (Number.isFinite(missedRate) && missedRate >= 0.35) || (Number.isFinite(recall) && recall <= 0.55);
    }).length;
    const predictiveWarnMachines = perMachineMetrics.filter((metric) => {
        const falseAlarmRate = Number(metric?.false_alarm_rate);
        const recall = Number(metric?.recall);
        return (Number.isFinite(falseAlarmRate) && falseAlarmRate >= 0.20 && falseAlarmRate < 0.35)
            || (Number.isFinite(recall) && recall > 0.55 && recall < 0.75);
    }).length;
    const critMachines = Math.max(liveCritMachines, predictiveCritMachines);
    const warnMachines = Math.max(liveWarnMachines, predictiveWarnMachines);
    const confidenceValues = history
        .map((h) => h?.predictions?.confidence)
        .filter((v) => typeof v === 'number' && Number.isFinite(v));
    const backendAvgConfidence = Number(fleetMetrics?.avg_confidence);
    const predictionConfidence = Number.isFinite(backendAvgConfidence) && backendAvgConfidence > 0
        ? backendAvgConfidence * 100
        : (confidenceValues.length > 0
            ? (confidenceValues.reduce((a, v) => a + v, 0) / confidenceValues.length) * 100
            : ((history[history.length - 1]?.predictions?.confidence || 0.95) * 100));
    const latestPrediction = history[history.length - 1]?.predictions;
    const predictionModelLabel = latestPrediction?.model_label
        || latestPrediction?.engine_version
        || 'XGBoost v3.1';
    const leadCoverage = Number(fleetMetrics?.lead_alert_coverage);
    const leadCoverageLabel = Number.isFinite(leadCoverage)
        ? `${(leadCoverage * 100).toFixed(1)}% lead coverage`
        : '+2.3% vs last shift';
    const labeledSamples = Number(fleetMetrics?.labeled_samples);
    const labeledSamplesLabel = Number.isFinite(labeledSamples)
        ? `${labeledSamples} labeled samples`
        : 'Target: <25 ppm';
    const brierScore = Number(fleetMetrics?.brier_score);
    const brierLabel = Number.isFinite(brierScore) ? `Brier ${brierScore.toFixed(3)}` : predictionModelLabel;

    const shiftData = useMemo(() => {
        const rows = history.slice(-180);
        if (rows.length < 3) {
            return [
                { shift: 'Morning', oee: 0, scraps: 0 },
                { shift: 'Evening', oee: 0, scraps: 0 },
                { shift: 'Night', oee: 0, scraps: 0 },
            ];
        }

        const chunkSize = Math.max(1, Math.floor(rows.length / 3));
        const windows = [
            rows.slice(0, chunkSize),
            rows.slice(chunkSize, chunkSize * 2),
            rows.slice(chunkSize * 2),
        ];
        const labels = ['Morning', 'Evening', 'Night'];

        return windows.map((windowRows, idx) => {
            const probs = windowRows
                .map((row) => row?.predictions?.scrap_probability)
                .filter((value) => typeof value === 'number' && Number.isFinite(value));
            if (probs.length === 0) {
                return { shift: labels[idx], oee: 0, scraps: 0 };
            }
            const avgProb = probs.reduce((acc, value) => acc + value, 0) / probs.length;
            return {
                shift: labels[idx],
                oee: Math.max(0, Math.min(100, Math.round((1 - avgProb) * 100))),
                scraps: +(avgProb * 100).toFixed(1),
            };
        });
    }, [history]);

    const scrapTrend = history.slice(-50).map((h, i) => ({
        idx: i,
        prob: h.predictions?.scrap_probability * 100 || 0
    }));

    const STATUS_LABEL = { ok: 'Nominal', warn: 'Drift Warning', crit: 'Critical' };
    const statusColor = { ok: 'var(--status-ok)', warn: 'var(--status-warn)', crit: 'var(--status-crit)' };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>

            {/* KPI row */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 'var(--space-4)' }}>
                <div className="stat-card info">
                    <div className="stat-label">Fleet OEE Avg</div>
                    <div className="stat-value">{overallOEE}<span className="stat-unit">%</span></div>
                    <div className="stat-delta positive" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                        <TrendingUp size={12} />{leadCoverageLabel}
                    </div>
                </div>
                <div className="stat-card warn">
                    <div className="stat-label">Total Scraps</div>
                    <div className="stat-value" style={{ color: 'var(--status-warn)' }}>{totalScraps}</div>
                    <div className="stat-delta negative" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                        <TrendingDown size={12} />{labeledSamplesLabel}
                    </div>
                </div>
                <div className="stat-card crit">
                    <div className="stat-label">Critical Status</div>
                    <div className="stat-value" style={{ color: critMachines > 0 ? 'var(--status-crit)' : 'var(--status-ok)' }}>{critMachines}</div>
                    <div className="stat-delta neutral">{warnMachines} in drift warning</div>
                </div>
                <div className="stat-card ok">
                    <div className="stat-label">Prediction Confidence</div>
                    <div className="stat-value" style={{ color: 'var(--status-ok)' }}>{predictionConfidence.toFixed(1)}<span className="stat-unit">%</span></div>
                    <div className="stat-delta positive" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                        <Award size={12} />{brierLabel}
                    </div>
                </div>
            </div>

            {/* Machine fleet cards */}
            <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: 'var(--space-4)', letterSpacing: '0.05em' }}>
                    Fleet Overview
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 'var(--space-4)' }}>
                    {machines.map(m => (
                        <div key={m.id} className={`card ${m.status}`} style={{ padding: 'var(--space-4)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                <div>
                                    <div style={{ fontSize: 14, fontWeight: 800, letterSpacing: '0.04em', color: 'var(--text-primary)' }}>{m.id}</div>
                                </div>
                                <div className="lamp-wrap">
                                    <div className={`lamp ${m.status}`} style={{ background: m.status === 'unknown' ? '#94a3b8' : undefined }} />
                                    <span style={{ fontSize: 11, color: m.status === 'unknown' ? '#94a3b8' : statusColor[m.status], fontWeight: 700 }}>
                                        {m.status === 'unknown' ? 'INITIALIZING' : STATUS_LABEL[m.status]}
                                    </span>
                                </div>
                            </div>

                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
                                <div>
                                    <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase' }}>OEE</div>
                                    <div style={{ fontSize: 18, fontWeight: 800, color: m.oee > 85 ? 'var(--status-ok)' : m.oee > 75 ? 'var(--status-warn)' : 'var(--status-crit)', fontFamily: 'JetBrains Mono, monospace' }}>{m.oee}%</div>
                                </div>
                                <div>
                                    <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Scraps</div>
                                    <div style={{ fontSize: 18, fontWeight: 800, color: m.scraps > 20 ? 'var(--status-crit)' : m.scraps > 5 ? 'var(--status-warn)' : 'var(--text-primary)', fontFamily: 'JetBrains Mono, monospace' }}>
                                        {Number.isFinite(perMachineMetricMap[m.id]?.observed_scrap_events)
                                            ? perMachineMetricMap[m.id].observed_scrap_events
                                            : m.scraps}
                                    </div>
                                </div>
                                <div>
                                    <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase' }}>{m.id === 'M231-11' ? 'Cushion' : 'Temp'}</div>
                                    <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--text-primary)', fontFamily: 'JetBrains Mono, monospace' }}>
                                        {m.id === 'M231-11' ? (m.cushion?.toFixed(2) || '---') : m.temp + '°'}
                                    </div>
                                </div>
                            </div>

                            <div className="progress-wrap">
                                <div className="progress-track" style={{ height: 5 }}>
                                    <div className={`progress-fill ${m.oee > 85 ? 'ok' : m.oee > 75 ? 'warn' : 'crit'}`} style={{ width: `${m.oee}%` }} />
                                </div>
                            </div>

                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-muted)', marginTop: 'auto' }}>
                                <span>{m.cycles.toLocaleString()} cycles</span>
                                {m.status !== 'ok' && (
                                    <span style={{ color: m.status === 'crit' ? 'var(--status-crit)' : 'var(--status-warn)', fontWeight: 800, display: 'flex', alignItems: 'center', gap: 4 }}>
                                        <AlertCircle size={12} />
                                        {m.status === 'crit' ? 'ACTION REQ.' : 'DRIFT'}
                                    </span>
                                )}
                            </div>

                            {/* AI Insights Tags */}
                            {m.abnormal_params && m.abnormal_params.length > 0 && (
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4, paddingTop: 8, borderTop: '1px solid var(--border-subtle)' }}>
                                    {m.abnormal_params.map(p => {
                                        const isPriority = ['Cushion', 'Dosage Time', 'Switch Position'].includes(p);
                                        return (
                                            <span key={p} className={isPriority ? 'badge-priority' : ''} style={{
                                                fontSize: 9, fontWeight: 800, borderRadius: 4,
                                                background: isPriority ? 'var(--accent-blue-dim)' : (m.status === 'crit' ? 'var(--status-crit-dim)' : 'var(--status-warn-dim)'),
                                                color: isPriority ? 'var(--accent-blue)' : (m.status === 'crit' ? 'var(--status-crit)' : 'var(--status-warn)'),
                                                padding: '2px 8px',
                                                textTransform: 'uppercase',
                                                letterSpacing: '0.05em',
                                                border: isPriority ? '1px solid var(--accent-blue)' : 'none'
                                            }}>
                                                {p}
                                            </span>
                                        )
                                    })}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            </div>

            {/* Charts row */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-5)' }}>
                <div className="card">
                    <div className="card-header">
                        <span className="card-title-large">Shift Performance Analytics</span>
                    </div>
                    <div style={{ height: 220 }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={shiftData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                                <XAxis dataKey="shift" tick={{ fontSize: 10, fill: '#64748b' }} tickLine={false} axisLine={false} />
                                <YAxis yAxisId="left" domain={[0, 100]} tick={{ fontSize: 10, fill: '#64748b' }} tickLine={false} axisLine={false} tickFormatter={v => `${v}%`} />
                                <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10, fill: '#64748b' }} tickLine={false} axisLine={false} />
                                <Tooltip
                                    contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, fontSize: 12, boxShadow: 'var(--shadow-card)' }}
                                    labelStyle={{ color: 'var(--text-primary)', fontWeight: 700 }}
                                />
                                <Legend wrapperStyle={{ fontSize: 11, paddingTop: 10 }} />
                                <Bar yAxisId="left" dataKey="oee" name="OEE %" fill="var(--accent-blue)" radius={[4, 4, 0, 0]} fillOpacity={0.8} />
                                <Bar yAxisId="right" dataKey="scraps" name="Scraps %" fill="var(--status-warn)" radius={[4, 4, 0, 0]} fillOpacity={0.8} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                <div className="card">
                    <div className="card-header">
                        <span className="card-title-large">Real-Time Fleet Scrap Risk</span>
                        <span className="badge badge-crit" style={{ fontSize: 10 }}>Live Stream</span>
                    </div>
                    <div style={{ height: 220 }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={scrapTrend} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                                <XAxis dataKey="idx" hide />
                                <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#64748b' }} tickLine={false} axisLine={false} tickFormatter={v => `${v}%`} />
                                <Tooltip
                                    contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, fontSize: 12, boxShadow: 'var(--shadow-card)' }}
                                    formatter={(v) => [`${v.toFixed(1)}%`, 'Scrap Risk']}
                                />
                                <Line dataKey="prob" name="Fleet Probability" stroke="var(--status-crit)" strokeWidth={3} dot={false} animationDuration={300} />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            </div>
        </div>
    );
}
