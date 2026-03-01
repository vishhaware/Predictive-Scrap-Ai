import {
    ComposedChart, Area, Line, Scatter, XAxis, YAxis, CartesianGrid,
    Tooltip, ResponsiveContainer, ReferenceLine, Legend,
} from 'recharts';
import { useMemo } from 'react';
import { formatTelemetryTimestamp } from '../utils/time';

const PARAM_META = {
    cushion: { label: 'Cushion', unit: 'mm', color: '#60a5fa' },
    injection_pressure: { label: 'Inj. Pressure', unit: 'bar', color: '#a78bfa' },
    switch_pressure: { label: 'Switch Pressure', unit: 'bar', color: '#34d399' },
    holding_pressure: { label: 'Holding Pressure', unit: 'bar', color: '#f472b6' },
    temp_z1: { label: 'Temp Zone 1', unit: '°C', color: '#facc15' },
    temp_z2: { label: 'Temp Zone 2', unit: '°C', color: '#f87171' },
    temp_z3: { label: 'Temp Zone 3', unit: '°C', color: '#ff9e6b' },
};

const CustomTooltip = ({ active, payload, label, unit }) => {
    if (!active || !payload?.length) return null;
    const entries = payload.filter(
        p =>
            p.value !== null &&
            p.value !== undefined &&
            !['cycle', 'cycleDisplay', 'idx', 'timestamp'].includes(String(p.dataKey))
    );
    const row = payload[0]?.payload;
    const cycleLabel = row?.cycleDisplay ?? label;

    const formatValue = (value) => {
        if (Array.isArray(value) && value.length === 2) {
            const [low, high] = value;
            const lowTxt = typeof low === 'number' ? low.toFixed(2) : String(low);
            const highTxt = typeof high === 'number' ? high.toFixed(2) : String(high);
            return `${lowTxt} - ${highTxt}`;
        }
        if (typeof value === 'number') {
            return value.toFixed(2);
        }
        return String(value);
    };

    return (
        <div style={{
            background: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-md)', padding: '10px 14px', fontSize: 12,
            boxShadow: 'var(--shadow-card)', minWidth: 160,
        }}>
            <div style={{ color: 'var(--text-muted)', marginBottom: 6, fontSize: 11 }}>Cycle #{cycleLabel}</div>
            <div style={{ color: 'var(--text-muted)', marginBottom: 8, fontSize: 11 }}>
                Time: {formatTelemetryTimestamp(row?.timestamp)}
            </div>
            {entries.map((e, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 3 }}>
                    <span style={{ color: e.color ?? 'var(--text-secondary)' }}>{e.name}</span>
                    <span style={{ fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, color: 'var(--text-primary)' }}>
                        {formatValue(e.value)} {unit}
                    </span>
                </div>
            ))}
        </div>
    );
};

export default function RangeAreaChart({ history, forecast, param, windowSize = 80 }) {
    const meta = PARAM_META[param] ?? { label: param, unit: '', color: '#60a5fa' };

    const chartData = useMemo(() => {
        const historySlice = history.slice(-windowSize);
        const historyData = historySlice.map((c, i) => {
            const tele = c.telemetry?.[param];
            if (!tele) return null;
            const min = tele.safe_min;
            const max = tele.safe_max;
            const val = tele.value;
            const set = tele.setpoint;
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
            };
        }).filter(Boolean);

        if (!forecast || !Array.isArray(forecast) || forecast.length === 0) {
            return historyData;
        }

        const lastCycle = historyData[historyData.length - 1]?.cycle || 0;
        const forecastData = forecast.map((f, i) => {
            const tele = f.telemetry?.[param];
            if (!tele) return null;
            const min = tele.safe_min;
            const max = tele.safe_max;
            const val = tele.value;
            const set = tele.setpoint;
            return {
                cycle: lastCycle + i + 1,
                cycleDisplay: lastCycle + i + 1,
                idx: historyData.length + i + 1,
                timestamp: f.timestamp,
                value: val,
                setpoint: set,
                safeMin: min,
                safeMax: max,
                band: min !== null && max !== null ? [min, max] : undefined,
                isForecast: true,
            };
        }).filter(Boolean);

        return [...historyData, ...forecastData];
    }, [history, forecast, param, windowSize]);

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

    // Compute Y-axis domain with padding
    const allVals = chartData.flatMap(d => [d.value, d.safeMin, d.safeMax].filter(v => v !== null));
    const yMin = Math.min(...allVals) * 0.97;
    const yMax = Math.max(...allVals) * 1.03;
    const uniqueCycleCount = new Set(chartData.map(d => d.cycle)).size;
    const xAxisKey = uniqueCycleCount < chartData.length ? 'idx' : 'cycle';

    return (
        <div style={{ height: 200 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>{meta.label}</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{meta.unit}</span>
                {hasViolation && (
                    <span className="badge badge-crit" style={{ fontSize: 10, padding: '2px 7px' }}>
                        ⚡ VIOLATION
                    </span>
                )}
            </div>
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
                    {chartData.some(d => d.isForecast) && (
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
