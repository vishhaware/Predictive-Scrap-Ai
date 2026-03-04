import {
    ComposedChart, Area, Line, Scatter, XAxis, YAxis, CartesianGrid,
    Tooltip, ResponsiveContainer, ReferenceLine, ReferenceArea, Legend,
} from 'recharts';
import { useMemo } from 'react';
import { formatTelemetryTimestamp } from '../utils/time';
import { useTelemetryStore } from '../store/useTelemetryStore';

const PARAM_META = {
    cushion: { label: 'Cushion', unit: 'mm', color: '#60a5fa' },
    injection_pressure: { label: 'Inj. Pressure', unit: 'bar', color: '#a78bfa' },
    switch_pressure: { label: 'Switch Pressure', unit: 'bar', color: '#34d399' },
    holding_pressure: { label: 'Holding Pressure', unit: 'bar', color: '#f472b6' },
    temp_z1: { label: 'Temp Zone 1', unit: '°C', color: '#facc15' },
    temp_z2: { label: 'Temp Zone 2', unit: '°C', color: '#f87171' },
    temp_z3: { label: 'Temp Zone 3', unit: '°C', color: '#ff9e6b' },
};

const CustomTooltip = ({ active, payload, unit }) => {
    if (!active || !payload?.length) return null;
    const row = payload[0]?.payload;
    const segment = row?.isForecast ? 'Future' : 'Past';
    const value = typeof row?.value === 'number' ? row.value.toFixed(2) : 'N/A';
    const setpoint = typeof row?.setpoint === 'number' ? row.setpoint.toFixed(2) : 'N/A';
    const safeMin = typeof row?.safeMin === 'number' ? row.safeMin.toFixed(2) : 'N/A';
    const safeMax = typeof row?.safeMax === 'number' ? row.safeMax.toFixed(2) : 'N/A';
    const volatility = typeof row?.volatility6pt === 'number' ? row.volatility6pt.toFixed(3) : '0.000';
    const hasConfidence = row?.confidenceUpper !== null && row?.confidenceLower !== null;
    const confidenceUpper = hasConfidence ? row.confidenceUpper.toFixed(3) : null;
    const confidenceLower = hasConfidence ? row.confidenceLower.toFixed(3) : null;

    return (
        <div style={{
            background: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-md)', padding: '10px 14px', fontSize: 12,
            boxShadow: 'var(--shadow-card)', minWidth: 160,
        }}>
            <div style={{ color: 'var(--text-muted)', marginBottom: 6, fontSize: 11 }}>Segment: {segment}</div>
            <div style={{ color: 'var(--text-muted)', marginBottom: 8, fontSize: 11 }}>
                Timestamp: {formatTelemetryTimestamp(row?.timestamp)}
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 3 }}>
                <span style={{ color: 'var(--text-secondary)' }}>Value</span>
                <span style={{ fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, color: 'var(--text-primary)' }}>{value} {unit}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 3 }}>
                <span style={{ color: 'var(--text-secondary)' }}>Setpoint</span>
                <span style={{ fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, color: 'var(--text-primary)' }}>{setpoint}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 3 }}>
                <span style={{ color: 'var(--text-secondary)' }}>Volatility (6-pt)</span>
                <span style={{ fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, color: 'var(--text-primary)' }}>{volatility}</span>
            </div>

            <div style={{ marginTop: 8, borderTop: '1px solid var(--border-subtle)', paddingTop: 6 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-muted)' }}>
                    <span>OK Range</span>
                    <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>{safeMin} - {safeMax}</span>
                </div>
                {hasConfidence && (
                    <div style={{ marginTop: 4, fontSize: 10, color: 'var(--text-muted)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', color: '#3b82f6' }}>
                            <span>Confidence Band</span>
                            <span style={{ fontWeight: 600 }}>{confidenceLower} - {confidenceUpper}</span>
                        </div>
                    </div>
                )}
                {row?.isForecast && (
                    <div style={{ marginTop: 4, padding: '2px 6px', background: 'var(--status-info-dim)', color: 'var(--status-info)', borderRadius: 4, fontWeight: 700, fontSize: 8, textAlign: 'center' }}>
                        Model label: forecasted
                    </div>
                )}
            </div>
        </div>
    );
};

export default function RangeAreaChart({
    history,
    forecast,
    param,
    windowSize = 80,
    showConfidenceBands = false,
    confidenceBands = null,
    violations = null,
    modelId = null,
}) {
    const meta = PARAM_META[param] ?? { label: param, unit: '', color: '#60a5fa' };
    const useHistoricalBaseline = useTelemetryStore(s => s.useHistoricalBaseline);

    const chartData = useMemo(() => {
        const rollingVolatility = (series) => {
            const out = [];
            const window = 6;
            for (let i = 0; i < series.length; i += 1) {
                const start = Math.max(0, i - window + 1);
                const chunk = series.slice(start, i + 1).filter((v) => Number.isFinite(v));
                if (chunk.length < 2) {
                    out.push(0);
                    continue;
                }
                const mean = chunk.reduce((sum, v) => sum + v, 0) / chunk.length;
                const variance = chunk.reduce((sum, v) => sum + ((v - mean) ** 2), 0) / chunk.length;
                out.push(Math.sqrt(Math.max(0, variance)));
            }
            return out;
        };

        const historySlice = history.slice(-windowSize);
        const historyTimes = historySlice
            .map(c => new Date(c?.timestamp).getTime())
            .filter(ms => Number.isFinite(ms))
            .sort((a, b) => a - b);
        const historyStepCandidates = [];
        for (let i = 1; i < historyTimes.length; i++) {
            const delta = historyTimes[i] - historyTimes[i - 1];
            if (delta > 0) historyStepCandidates.push(delta);
        }
        const fallbackStepMs = historyStepCandidates.length > 0
            ? historyStepCandidates[Math.floor(historyStepCandidates.length / 2)]
            : 60_000;
        const lastHistoryMs = historyTimes.length > 0 ? historyTimes[historyTimes.length - 1] : Date.now();

        const historyData = historySlice.map((c, i) => {
            const tele = c.telemetry?.[param];
            if (!tele) return null;
            const val = tele.value;
            const histSet = tele.setpoint;
            const offSet = tele.official_setpoint ?? histSet;
            const set = useHistoricalBaseline ? histSet : offSet;

            const tol = (tele.safe_max !== null && histSet !== null) ? (tele.safe_max - histSet) : 0;
            const min = useHistoricalBaseline ? tele.safe_min : (set !== null ? set - tol : null);
            const max = useHistoricalBaseline ? tele.safe_max : (set !== null ? set + tol : null);

            const isViolation = (min !== null && val < min) || (max !== null && val > max);
            const parsedCycle = Number(c.cycle_id);
            const cycle = Number.isFinite(parsedCycle) ? parsedCycle : i + 1;
            return {
                cycle,
                cycleDisplay: c.cycle_id ?? i + 1,
                idx: i + 1,
                timestamp: c.timestamp,
                value: val,
                setpoint: set,
                safeMin: min,
                safeMax: max,
                band: min !== null && max !== null ? [min, max] : undefined,
                violation: isViolation ? val : null,
                isForecast: false,
                volatility6pt: 0,
            };
        }).filter(Boolean);

        if (!forecast || !Array.isArray(forecast) || forecast.length === 0) {
            const vols = rollingVolatility(historyData.map((row) => row.value));
            return historyData.map((row, idx) => ({ ...row, volatility6pt: vols[idx] || 0 }));
        }

        const lastCycle = historyData[historyData.length - 1]?.cycle || 0;
        const forecastData = forecast.map((f, i) => {
            const tele = f.telemetry?.[param];
            if (!tele) return null;
            const val = tele.value;
            const histSet = tele.setpoint;
            const offSet = tele.official_setpoint ?? histSet;
            const set = useHistoricalBaseline ? histSet : offSet;

            const tol = (tele.safe_max !== null && histSet !== null) ? (tele.safe_max - histSet) : 0;
            const min = useHistoricalBaseline ? tele.safe_min : (set !== null ? set - tol : null);
            const max = useHistoricalBaseline ? tele.safe_max : (set !== null ? set + tol : null);

            const rawForecastMs = new Date(f?.timestamp).getTime();
            const ensuredForecastMs = Number.isFinite(rawForecastMs) && rawForecastMs > lastHistoryMs
                ? rawForecastMs
                : (lastHistoryMs + fallbackStepMs * (i + 1));
            return {
                cycle: lastCycle + i + 1,
                cycleDisplay: lastCycle + i + 1,
                idx: historyData.length + i + 1,
                timestamp: new Date(ensuredForecastMs).toISOString(),
                value: val,
                setpoint: set,
                safeMin: min,
                safeMax: max,
                band: min !== null && max !== null ? [min, max] : undefined,
                isForecast: true,
                volatility6pt: 0,
            };
        }).filter(Boolean);

        const combined = [...historyData, ...forecastData];
        const vols = rollingVolatility(combined.map((row) => row.value));
        return combined.map((row, idx) => ({ ...row, volatility6pt: vols[idx] || 0 }));
    }, [history, forecast, param, windowSize, confidenceBands, showConfidenceBands]);

    if (chartData.length === 0) {
        return (
            <div style={{ height: 200 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>{meta.label}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{meta.unit}</span>
                </div>
                <div
                    style={{
                        height: '82%',
                        border: '1px dashed var(--border-subtle)',
                        borderRadius: 'var(--radius-sm)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: 'var(--text-muted)',
                        fontSize: 12,
                        background: 'var(--bg-elevated)',
                    }}
                >
                    No telemetry data available
                </div>
            </div>
        );
    }

    const hasViolation = chartData.some(d => d.violation !== null);
    const hasForecast = chartData.some(d => d.isForecast);
    const forecastStartPoint = hasForecast ? chartData.find(d => d.isForecast) : null;
    const forecastEndPoint = hasForecast ? chartData[chartData.length - 1] : null;
    const historyOnly = chartData.filter(d => !d.isForecast);
    const historyStartPoint = historyOnly.length > 0 ? historyOnly[0] : null;
    const historyEndPoint = historyOnly.length > 0 ? historyOnly[historyOnly.length - 1] : null;

    const allVals = chartData.flatMap(d => [d.value, d.safeMin, d.safeMax].filter(v => v !== null));
    const yMin = Math.min(...allVals) * 0.97;
    const yMax = Math.max(...allVals) * 1.03;

    // Latest stats for header
    const latestPoint = historyOnly.length > 0 ? historyOnly[historyOnly.length - 1] : null;
    const curVal = latestPoint?.value;
    const setPoint = latestPoint?.setpoint;
    const delta = (curVal !== null && setPoint !== null) ? (curVal - setPoint) : null;
    const tol = latestPoint ? (latestPoint.safeMax - latestPoint.setpoint) : 0;
    const deltaRatio = (delta !== null && tol > 0) ? (Math.abs(delta) / tol).toFixed(1) : null;
    let driftPerHour = null;
    if (historyOnly.length >= 2) {
        const startIdx = Math.max(0, historyOnly.length - 6);
        const first = historyOnly[startIdx];
        const last = historyOnly[historyOnly.length - 1];
        const firstTs = new Date(first.timestamp).getTime();
        const lastTs = new Date(last.timestamp).getTime();
        if (Number.isFinite(firstTs) && Number.isFinite(lastTs) && lastTs > firstTs) {
            const deltaHours = (lastTs - firstTs) / 3_600_000;
            driftPerHour = (last.value - first.value) / deltaHours;
        }
    }

    return (
        <div style={{ height: 200 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>{meta.label}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{meta.unit}</span>
                    {hasViolation && (
                        <span className="badge badge-crit" style={{ fontSize: 9, padding: '1px 6px' }}>
                            VIOLATION
                        </span>
                    )}
                </div>

                {curVal !== null && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 11, fontWeight: 600 }}>
                        <div style={{ color: 'var(--text-muted)' }}>
                            SET: <span style={{ color: 'var(--text-primary)', fontFamily: 'JetBrains Mono' }}>{setPoint?.toFixed(2) ?? '---'}</span>
                        </div>
                        <div style={{ color: 'var(--text-muted)' }}>
                            CUR: <span style={{ color: 'var(--text-primary)', fontFamily: 'JetBrains Mono' }}>{curVal.toFixed(2)}</span>
                        </div>
                        {delta !== null && (
                            <div style={{
                                color: hasViolation ? 'var(--status-crit)' : 'var(--status-ok)',
                                background: hasViolation ? 'var(--status-crit-dim)' : 'var(--status-ok-dim)',
                                padding: '1px 6px',
                                borderRadius: 4,
                                fontFamily: 'JetBrains Mono'
                            }}>
                                Δ {delta > 0 ? '+' : ''}{delta.toFixed(2)}
                                {deltaRatio > 1 && <span style={{ fontSize: 9, marginLeft: 4 }}>({deltaRatio}x TOL)</span>}
                            </div>
                        )}
                    </div>
                )}
            </div>
            {driftPerHour !== null && (
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>
                    Trend: {driftPerHour >= 0 ? '↑' : '↓'} {Math.abs(driftPerHour).toFixed(3)} {meta.unit}/hr
                </div>
            )}
            {hasForecast && historyStartPoint && historyEndPoint && forecastStartPoint && forecastEndPoint && (
                <div style={{ display: 'flex', gap: 12, marginBottom: 6, fontSize: 10, color: 'var(--text-muted)' }}>
                    <span>
                        <strong style={{ color: 'var(--text-secondary)' }}>Past:</strong>{' '}
                        {formatTelemetryTimestamp(historyStartPoint.timestamp)} to {formatTelemetryTimestamp(historyEndPoint.timestamp)}
                    </span>
                    <span>
                        <strong style={{ color: 'var(--accent-blue-lt)' }}>Future:</strong>{' '}
                        {formatTelemetryTimestamp(forecastStartPoint.timestamp)} to {formatTelemetryTimestamp(forecastEndPoint.timestamp)}
                    </span>
                </div>
            )}
            <ResponsiveContainer width="100%" height="85%">
                <ComposedChart data={chartData} margin={{ top: 4, right: 10, left: -10, bottom: 0 }}>
                    <defs>
                        <linearGradient id={`band-${param}`} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor={meta.color} stopOpacity={0.12} />
                            <stop offset="95%" stopColor={meta.color} stopOpacity={0.03} />
                        </linearGradient>
                    </defs>

                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                    <XAxis
                        dataKey="timestamp"
                        tick={{ fontSize: 10, fill: '#64748b' }}
                        tickLine={false}
                        axisLine={false}
                        tickFormatter={(v) => formatTelemetryTimestamp(v)}
                        minTickGap={40}
                    />
                    <YAxis domain={[yMin, yMax]} tick={{ fontSize: 10, fill: '#64748b' }} tickLine={false} axisLine={false} width={36} tickFormatter={v => v.toFixed(1)} />
                    <Tooltip content={<CustomTooltip unit={meta.unit} />} />

                    {/* Future zone highlight and split marker */}
                    {hasForecast && forecastStartPoint && forecastEndPoint && (
                        <>
                            <ReferenceArea
                                x1={forecastStartPoint.timestamp}
                                x2={forecastEndPoint.timestamp}
                                y1={yMin}
                                y2={yMax}
                                fill={meta.color}
                                fillOpacity={0.06}
                                ifOverflow="extendDomain"
                            />
                            <ReferenceLine
                                x={forecastStartPoint.timestamp}
                                stroke={meta.color}
                                strokeDasharray="2 4"
                                strokeOpacity={0.8}
                                ifOverflow="extendDomain"
                                label={{ value: 'Past -> Future seam', position: 'insideTopRight', fontSize: 10, fill: '#475569' }}
                            />
                        </>
                    )}

                    {/* Safe envelope band */}
                    {chartData[0]?.band && (
                        <Area
                            dataKey="band"
                            name="Safe Band"
                            fill={`url(#band-${param})`}
                            stroke={meta.color}
                            strokeWidth={0}
                            strokeOpacity={0.35}
                            fillOpacity={1}
                            activeDot={false}
                            legendType="none"
                        />
                    )}

                    {/* Upper & lower bound lines */}
                    {chartData[0]?.safeMax !== null && (
                        <Line dataKey="safeMax" name="Upper Bound" stroke={meta.color} strokeWidth={1} strokeDasharray="5 4" dot={false} strokeOpacity={0.5} legendType="none" />
                    )}
                    {chartData[0]?.safeMin !== null && (
                        <Line dataKey="safeMin" name="Lower Bound" stroke={meta.color} strokeWidth={1} strokeDasharray="5 4" dot={false} strokeOpacity={0.5} legendType="none" />
                    )}

                    {/* Setpoint centerline */}
                    {chartData.some(d => d.setpoint !== null) && (
                        <Line dataKey="setpoint" name="Setpoint" stroke={meta.color} strokeWidth={1} strokeDasharray="2 3" dot={false} strokeOpacity={0.7} legendType="none" />
                    )}

                    {/* Measured value (History) */}
                    <Line
                        dataKey="value"
                        name={meta.label}
                        stroke={meta.color}
                        strokeWidth={2}
                        dot={false}
                        activeDot={{ r: 4, fill: meta.color }}
                        connectNulls
                        data={chartData.filter(d => !d.isForecast)}
                    />

                    {/* Predicted value (Forecast) */}
                    {hasForecast && (
                        <Line
                            dataKey="value"
                            name={`${meta.label} (Forecast)`}
                            stroke={meta.color}
                            strokeWidth={2}
                            strokeDasharray="4 4"
                            dot={false}
                            activeDot={{ r: 4, fill: meta.color }}
                            connectNulls
                            data={chartData.filter(d => d.isForecast || d === chartData[chartData.findIndex(x => x.isForecast) - 1])}
                        />
                    )}

                    {/* Violation scatter */}
                    {hasViolation && (
                        <Scatter
                            dataKey="violation"
                            name="Violation"
                            fill="var(--status-crit)"
                            shape={<DiamondShape />}
                        />
                    )}
                </ComposedChart>
            </ResponsiveContainer>
        </div>
    );
}

function DiamondShape({ cx, cy }) {
    if (cx == null || cy == null) return null;
    const size = 5;
    const path = `M ${cx} ${cy - size} L ${cx + size} ${cy} L ${cx} ${cy + size} L ${cx - size} ${cy} Z`;
    return <path d={path} fill="var(--status-crit)" stroke="var(--status-crit-dim)" strokeWidth={1} />;
}
