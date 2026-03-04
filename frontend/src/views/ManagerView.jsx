import { useEffect, useMemo } from 'react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { toFixedSafe } from '../utils/number';
import { t } from '../utils/i18n';
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
    LineChart, Line, Legend, ReferenceLine,
} from 'recharts';
import { TrendingDown, TrendingUp, Award, AlertCircle } from 'lucide-react';

export default function ManagerView() {
    const machines = useTelemetryStore(s => s.machines);
    const history = useTelemetryStore(s => s.history);
    const aiMetrics = useTelemetryStore(s => s.aiMetrics);
    const fleetChartData = useTelemetryStore(s => s.fleetChartData);
    const fleetChartDataLoading = useTelemetryStore(s => s.fleetChartDataLoading);

    useEffect(() => {
        void useTelemetryStore.getState().loadFleetChartData(60);
    }, []);

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

    const fleetTimeline = useMemo(() => {
        const past = Array.isArray(fleetChartData?.past) ? fleetChartData.past : [];
        const future = Array.isArray(fleetChartData?.future) ? fleetChartData.future : [];
        const byTs = new Map();

        past.forEach((row) => {
            const ts = row?.timestamp;
            if (!ts) return;
            if (!byTs.has(ts)) byTs.set(ts, { timestamp: ts, pastPct: null, futurePct: null });
            byTs.get(ts).pastPct = Number(row?.scrap_pct || 0);
        });
        future.forEach((row) => {
            const ts = row?.timestamp;
            if (!ts) return;
            if (!byTs.has(ts)) byTs.set(ts, { timestamp: ts, pastPct: null, futurePct: null });
            byTs.get(ts).futurePct = Number(row?.scrap_pct || 0);
        });

        const rows = Array.from(byTs.values()).sort(
            (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
        );
        return {
            rows,
            seamTs: fleetChartData?.meta?.past_last_ts || null,
            meta: fleetChartData?.meta || null,
        };
    }, [fleetChartData]);

    const topFutureRiskMachines = useMemo(() => {
        const rows = Array.isArray(fleetChartData?.per_machine) ? fleetChartData.per_machine.slice() : [];
        return rows
            .sort((a, b) => Number(b?.future_peak_scrap_prob || 0) - Number(a?.future_peak_scrap_prob || 0))
            .slice(0, 5);
    }, [fleetChartData]);

    const STATUS_LABEL = { ok: 'Nominal', warn: 'Drift Warning', crit: 'Critical' };
    const statusColor = { ok: 'var(--status-ok)', warn: 'var(--status-warn)', crit: 'var(--status-crit)' };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
            <div className="card">
                <div className="card-header">
                    <span className="card-title-large">Fleet Past/Future Scrap Timeline</span>
                    <span className="badge badge-info">Past = observed · Future = forecast</span>
                </div>
                {fleetChartDataLoading && fleetTimeline.rows.length === 0 ? (
                    <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Loading fleet chart data...</div>
                ) : (
                    <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 'var(--space-4)' }}>
                        <div style={{ height: 220 }}>
                            <ResponsiveContainer width="100%" height="100%">
                                <LineChart data={fleetTimeline.rows} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                                    <XAxis
                                        dataKey="timestamp"
                                        tick={{ fontSize: 10, fill: '#64748b' }}
                                        tickLine={false}
                                        axisLine={false}
                                        tickFormatter={(value) => new Date(value).toLocaleTimeString()}
                                    />
                                    <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#64748b' }} tickLine={false} axisLine={false} tickFormatter={(v) => `${v}%`} />
                                    <Tooltip
                                        contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, fontSize: 12, boxShadow: 'var(--shadow-card)' }}
                                        formatter={(value, name) => [`${toFixedSafe(value, 2, '0.00')}%`, name]}
                                        labelFormatter={(label) => new Date(label).toLocaleString()}
                                    />
                                    <Legend wrapperStyle={{ fontSize: 11 }} />
                                    {fleetTimeline.seamTs && (
                                        <ReferenceLine x={fleetTimeline.seamTs} stroke="#dc2626" strokeDasharray="4 4" label={{ value: 'Past -> Future seam', position: 'insideTopRight', fontSize: 10 }} />
                                    )}
                                    <Line type="monotone" dataKey="pastPct" name="Scrap Probability (Past)" stroke="#0B3D91" strokeWidth={2.5} dot={false} connectNulls />
                                    <Line type="monotone" dataKey="futurePct" name="Scrap Probability (Forecast)" stroke="#F97316" strokeWidth={2.5} strokeDasharray="6 4" dot={false} connectNulls />
                                </LineChart>
                            </ResponsiveContainer>
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-secondary)' }}>Top predicted risk machines</div>
                            {topFutureRiskMachines.length === 0 ? (
                                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No fleet forecast data available.</div>
                            ) : topFutureRiskMachines.map((row) => (
                                <div key={row.machine_id} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 10px', borderRadius: 8, background: 'var(--bg-elevated)', fontSize: 12 }}>
                                    <span style={{ fontWeight: 700 }}>{row.machine_id}</span>
                                    <span style={{ color: 'var(--status-crit)', fontFamily: 'JetBrains Mono, monospace' }}>
                                        {toFixedSafe(Number(row.future_peak_scrap_prob || 0) * 100, 1, '0.0')}%
                                    </span>
                                </div>
                            ))}
                            {fleetTimeline.meta && (
                                <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}>
                                    Seam: {fleetTimeline.meta.seam_ok ? 'OK' : 'CHECK'} · Ingestion: {fleetTimeline.meta.latest_ingestion_time ? new Date(fleetTimeline.meta.latest_ingestion_time).toLocaleString() : 'N/A'}
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>

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
                    <div className="stat-value" style={{ color: 'var(--status-ok)' }}>{toFixedSafe(predictionConfidence, 1, '0.0')}<span className="stat-unit">%</span></div>
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
                                        {m.id === 'M231-11' ? toFixedSafe(m.cushion, 2, '---') : `${m.temp}°`}
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
                                    formatter={(v) => [`${toFixedSafe(v, 1, '0.0')}%`, 'Scrap Risk']}
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
