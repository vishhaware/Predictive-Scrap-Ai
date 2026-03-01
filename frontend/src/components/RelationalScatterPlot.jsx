import {
    ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
    ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { useMemo } from 'react';

function CustomTooltip({ active, payload }) {
    if (!active || !payload?.length) return null;
    const d = payload[0]?.payload;
    const yLabel = d?.yLabel || 'Secondary Pressure';
    return (
        <div style={{
            background: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-md)', padding: '10px 14px', fontSize: 12,
        }}>
            <div style={{ color: 'var(--text-muted)', marginBottom: 4 }}>Cycle #{d?.cycleId}</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                <span style={{ color: 'var(--text-secondary)' }}>Inj. Pressure</span>
                <span style={{ fontFamily: 'JetBrains Mono, monospace', fontWeight: 700 }}>{d?.ip} bar</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                <span style={{ color: 'var(--text-secondary)' }}>{yLabel}</span>
                <span style={{ fontFamily: 'JetBrains Mono, monospace', fontWeight: 700 }}>{d?.yp} bar</span>
            </div>
            <div style={{
                marginTop: 6, padding: '3px 8px', borderRadius: 4,
                background: d?.violation ? 'var(--status-crit-dim)' : 'var(--status-ok-dim)',
                color: d?.violation ? 'var(--status-crit)' : 'var(--status-ok)',
                fontWeight: 700, fontSize: 11,
            }}>
                Ratio {d?.ratio} {d?.violation ? '— OUTLIER' : '— NORMAL'}
            </div>
        </div>
    );
}

export default function RelationalScatterPlot({ history, windowSize = 200 }) {
    const derived = useMemo(() => {
        const rows = history.slice(-windowSize).map((cycle) => {
            const ipRaw = cycle?.telemetry?.injection_pressure?.value;
            const holdRaw = cycle?.telemetry?.holding_pressure?.value;
            const switchRaw = cycle?.telemetry?.switch_pressure?.value;

            const ip = Number(ipRaw);
            const hold = Number(holdRaw);
            const sw = Number(switchRaw);

            const hasHold = Number.isFinite(hold);
            const hasSwitch = Number.isFinite(sw);
            const yp = hasHold ? hold : (hasSwitch ? sw : NaN);
            if (!Number.isFinite(ip) || !Number.isFinite(yp) || ip === 0) return null;

            const yLabel = hasHold ? 'Hold Pressure' : 'Switch Pressure';
            return {
                ip,
                yp,
                ratio: yp / ip,
                cycleId: cycle?.cycle_id,
                yLabel,
            };
        }).filter(Boolean);

        if (rows.length === 0) {
            return { data: [], ratioMean: 0, ratioStd: 0, yLabel: 'Secondary Pressure' };
        }

        const ratios = rows.map((item) => item.ratio);
        const ratioMean = ratios.reduce((a, b) => a + b, 0) / ratios.length;
        const variance = ratios.reduce((acc, value) => acc + ((value - ratioMean) ** 2), 0) / Math.max(1, ratios.length - 1);
        const ratioStd = Math.sqrt(Math.max(0, variance));

        const data = rows.map((item) => {
            const z = ratioStd > 1e-6 ? Math.abs(item.ratio - ratioMean) / ratioStd : 0;
            return {
                ...item,
                ratio: `${item.ratio.toFixed(3)}x`,
                violation: z > 2.0,
            };
        });

        return {
            data,
            ratioMean,
            ratioStd,
            yLabel: rows[0].yLabel,
        };
    }, [history, windowSize]);

    const { data, ratioMean, ratioStd, yLabel } = derived;

    const ok = data.filter(d => !d.violation);
    const viol = data.filter(d => d.violation);
    const hasData = data.length > 0;

    // Range extents
    const ipMax = hasData ? Math.max(...data.map(d => d.ip), 135) : 135;
    const ipMin = hasData ? Math.min(...data.map(d => d.ip), 105) : 105;

    const lowRatio = Math.max(0, ratioMean - (2 * ratioStd));
    const highRatio = ratioMean + (2 * ratioStd);
    const bandLow = [{ ip: ipMin, yp: ipMin * lowRatio }, { ip: ipMax, yp: ipMax * lowRatio }];
    const bandHigh = [{ ip: ipMin, yp: ipMin * highRatio }, { ip: ipMax, yp: ipMax * highRatio }];

    return (
        <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>
                    {yLabel} vs. Injection Pressure
                </span>
                <span className="badge badge-neutral" style={{ fontSize: 10 }}>Live Correlation View</span>
                <div style={{ display: 'flex', gap: 10, marginLeft: 'auto', fontSize: 11 }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--status-ok)', display: 'inline-block' }} />
                        <span style={{ color: 'var(--text-muted)' }}>Normal (within dynamic band)</span>
                    </span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--status-crit)', display: 'inline-block' }} />
                        <span style={{ color: 'var(--text-muted)' }}>Outlier</span>
                    </span>
                </div>
            </div>

            <div style={{ height: 260, position: 'relative' }}>
                {!hasData && (
                    <div style={{
                        position: 'absolute',
                        inset: 0,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: 'var(--text-muted)',
                        fontSize: 12,
                        border: '1px dashed var(--border-subtle)',
                        borderRadius: 8,
                        zIndex: 1,
                        background: 'var(--bg-elevated)'
                    }}>
                        No pressure-pair data available in current history window.
                    </div>
                )}
                <ResponsiveContainer width="100%" height="100%">
                    <ScatterChart margin={{ top: 6, right: 12, left: -8, bottom: 4 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis
                            dataKey="ip" type="number" name="Inj. Pressure" domain={['auto', 'auto']}
                            tick={{ fontSize: 10, fill: '#64748b' }} tickLine={false} axisLine={false}
                            label={{ value: 'Injection Pressure (bar)', position: 'insideBottom', offset: -2, fontSize: 10, fill: '#64748b' }}
                        />
                        <YAxis
                            dataKey="yp" type="number" name={yLabel} domain={['auto', 'auto']}
                            tick={{ fontSize: 10, fill: '#64748b' }} tickLine={false} axisLine={false}
                            label={{ value: `${yLabel} (bar)`, angle: -90, position: 'insideLeft', offset: 10, fontSize: 10, fill: '#64748b' }}
                        />
                        <Tooltip content={<CustomTooltip />} cursor={{ strokeDasharray: '3 3', stroke: 'var(--border-default)' }} />

                        {/* Dynamic band from observed ratio mean +/- 2 std */}
                        <ReferenceLine
                            segment={bandLow}
                            stroke="var(--status-warn)" strokeWidth={1} strokeDasharray="5 4" strokeOpacity={0.7}
                            label={{ value: `Low ${lowRatio.toFixed(2)}x`, position: 'right', fontSize: 10, fill: 'var(--status-warn)' }}
                        />
                        <ReferenceLine
                            segment={bandHigh}
                            stroke="var(--status-warn)" strokeWidth={1} strokeDasharray="5 4" strokeOpacity={0.7}
                            label={{ value: `High ${highRatio.toFixed(2)}x`, position: 'right', fontSize: 10, fill: 'var(--status-warn)' }}
                        />

                        {/* OK cycles */}
                        <Scatter
                            name="OK"
                            data={ok}
                            fill="var(--status-ok)"
                            fillOpacity={0.55}
                        />

                        {/* Violation cycles */}
                        <Scatter
                            name="Violation"
                            data={viol}
                            fill="var(--status-crit)"
                            fillOpacity={0.85}
                        />
                    </ScatterChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
}
