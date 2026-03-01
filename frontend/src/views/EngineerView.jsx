import { useState, useMemo } from 'react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import RangeAreaChart from '../components/RangeAreaChart';
import RelationalScatterPlot from '../components/RelationalScatterPlot';
import RootCausePanel from '../components/RootCausePanel';
import {
    LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { Play, Pause, SkipBack, SkipForward, TrendingUp } from 'lucide-react';
import { formatTelemetryTimestamp } from '../utils/time';

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
const PARAM_LABELS = {
    cushion: 'Cushion (mm)', injection_pressure: 'Inj. Pressure (bar)',
    switch_pressure: 'Switch Pressure (bar)',
    shot_size: 'Shot Size (mm)',
    ejector_torque: 'Ejector Torque (Nm)',
    temp_z8: 'Temp Z8 (°C)',
    temp_z1: 'Temp Z1 (°C)', temp_z2: 'Temp Z2 (°C)', temp_z3: 'Temp Z3 (°C)',
};

export default function EngineerView() {
    const history = useTelemetryStore(s => s.history);
    const latest = useTelemetryStore(s => s.latest);
    const replayIndex = useTelemetryStore(s => s.replayIndex);
    const setReplayIdx = useTelemetryStore(s => s.setReplayIndex);

    const [activeTab, setActiveTab] = useState('telemetry');
    const [maWindow, setMaWindow] = useState(20);
    const [isPlaying, setIsPlaying] = useState(false);

    const telemetryParams = useMemo(() => {
        const latestTelemetry = latest?.telemetry || {};
        const available = Object.keys(latestTelemetry);
        const ordered = PREFERRED_PARAMS.filter((param) => available.includes(param));
        const fallback = available
            .filter((param) => !ordered.includes(param))
            .slice(0, 8 - ordered.length);
        return [...ordered, ...fallback].slice(0, 8);
    }, [latest]);

    // DVR replay
    const replayCycle = history[replayIndex];

    // Moving average computation for scrap probability trend
    const scrapTrend = useMemo(() => {
        return history.map((c, i) => {
            const start = Math.max(0, i - maWindow + 1);
            const slice = history.slice(start, i + 1);
            const ma = slice.reduce((sum, x) => sum + (x?.predictions?.scrap_probability || 0), 0) / slice.length;
            return {
                cycle: Number(c.cycle_id),
                timestamp: c.timestamp,
                raw: +(((c?.predictions?.scrap_probability || 0) * 100).toFixed(2)),
                ma: +(ma * 100).toFixed(2),
            };
        }).slice(-200);
    }, [history, maWindow]);

    // DVR playback
    function handlePlay() {
        if (isPlaying) { setIsPlaying(false); return; }
        setIsPlaying(true);
        let idx = replayIndex;
        const timer = setInterval(() => {
            idx++;
            if (idx >= history.length) { clearInterval(timer); setIsPlaying(false); return; }
            setReplayIdx(idx);
        }, 120);
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>

            {/* Tab selector */}
            <div className="tabs">
                {[
                    { id: 'telemetry', label: 'Multi-Param Telemetry' },
                    { id: 'relational', label: 'Relational Plot' },
                    { id: 'trend', label: 'Scrap Trend + MA' },
                    { id: 'dvr', label: 'DVR Playback' },
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

            {/* ── TELEMETRY GRID ── */}
            {activeTab === 'telemetry' && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 'var(--space-4)' }}>
                    {telemetryParams.map(param => (
                        <div key={param} className="card">
                            <RangeAreaChart history={history} param={param} windowSize={80} />
                        </div>
                    ))}
                </div>
            )}

            {/* ── RELATIONAL SCATTER ── */}
            {activeTab === 'relational' && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-5)' }}>
                    <div className="card">
                        <div className="card-header">
                            <span className="card-title-large">Pressure Correlation View</span>
                        </div>
                        <RelationalScatterPlot history={history} windowSize={200} />
                    </div>
                    <div className="card">
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

            {/* ── SCRAP TREND ── */}
            {activeTab === 'trend' && (
                <div className="card">
                    <div className="card-header">
                        <span className="card-title-large">Scrap Probability Trend + Moving Average</span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <TrendingUp size={14} color="var(--accent-blue-lt)" />
                            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>MA Window:</span>
                            <select
                                value={maWindow}
                                onChange={e => setMaWindow(Number(e.target.value))}
                                style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border-default)', color: 'var(--text-primary)', borderRadius: 6, padding: '3px 8px', fontSize: 12, cursor: 'pointer' }}
                            >
                                {[5, 10, 20, 50].map(v => <option key={v} value={v}>{v} cycles</option>)}
                            </select>
                        </div>
                    </div>
                    <div style={{ height: 320 }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={scrapTrend} margin={{ top: 4, right: 16, left: -8, bottom: 4 }}>
                                <defs>
                                    <linearGradient id="scrapGrad" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="0%" stopColor="var(--status-crit)" stopOpacity={0.4} />
                                        <stop offset="100%" stopColor="var(--status-crit)" stopOpacity={0} />
                                    </linearGradient>
                                </defs>
                                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                                <XAxis dataKey="cycle" tick={{ fontSize: 10, fill: '#64748b' }} tickLine={false} axisLine={false} />
                                <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#64748b' }} tickLine={false} axisLine={false} tickFormatter={v => `${v}%`} />
                                <Tooltip
                                    contentStyle={{ background: 'var(--bg-elevated)', border: '1px solid var(--border-default)', borderRadius: 8, fontSize: 12 }}
                                    formatter={(v, n) => [`${v.toFixed(1)}%`, n]}
                                    labelFormatter={(l, payload) => {
                                        const entry = payload?.[0]?.payload;
                                        return (
                                            <div>
                                                <div style={{ fontWeight: 700 }}>Cycle #{entry?.cycle}</div>
                                                <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{formatTelemetryTimestamp(entry?.timestamp)}</div>
                                            </div>
                                        );
                                    }}
                                />
                                <Legend wrapperStyle={{ fontSize: 12, color: 'var(--text-secondary)' }} />
                                <Line dataKey="raw" name="Raw Probability" stroke="var(--status-crit)" strokeWidth={1} dot={false} strokeOpacity={0.5} />
                                <Line dataKey="ma" name={`MA-${maWindow}`} stroke="var(--accent-blue-lt)" strokeWidth={2.5} dot={false} />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                    <div style={{ marginTop: 'var(--space-4)', padding: '12px 16px', background: 'var(--bg-elevated)', borderRadius: 'var(--radius-md)', fontSize: 12, color: 'var(--text-secondary)' }}>
                        <strong style={{ color: 'var(--text-primary)' }}>Statistical Insight:</strong> The MA-{maWindow} overlay reveals macro degradation trend not visible in raw signal.
                        A gradient shift in the moving average after cycle ~84680 indicates progressive cushion collapse due to check-ring wear.
                    </div>
                </div>
            )}

            {/* ── DVR PLAYBACK ── */}
            {activeTab === 'dvr' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
                    {/* Playback controls */}
                    <div className="card">
                        <div className="card-header">
                            <span className="card-title-large">DVR Cycle Replay</span>
                            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                                <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, color: 'var(--text-secondary)' }}>
                                    Cycle #{replayCycle?.cycle_id} &nbsp;|&nbsp; {replayIndex + 1} / {history.length}
                                </span>
                                <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: 'var(--text-muted)' }}>
                                    {formatTelemetryTimestamp(replayCycle?.timestamp)}
                                </span>
                            </div>
                        </div>

                        {/* Scrubber */}
                        <div style={{ marginBottom: 'var(--space-4)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-muted)', marginBottom: 6 }}>
                                <span>#{history[0]?.cycle_id}</span>
                                <span>#{history[history.length - 1]?.cycle_id}</span>
                            </div>
                            <input
                                type="range"
                                min={0} max={history.length - 1} value={replayIndex}
                                onChange={e => setReplayIdx(Number(e.target.value))}
                                style={{ width: '100%' }}
                            />
                        </div>

                        {/* Transport controls */}
                        <div style={{ display: 'flex', gap: 'var(--space-3)', justifyContent: 'center' }}>
                            <button className="btn btn-ghost btn-icon" onClick={() => setReplayIdx(0)}>
                                <SkipBack size={15} />
                            </button>
                            <button className="btn btn-ghost btn-icon" onClick={() => setReplayIdx(Math.max(0, replayIndex - 1))}>
                                <SkipBack size={15} />
                            </button>
                            <button className="btn btn-primary" onClick={handlePlay}>
                                {isPlaying ? <Pause size={15} /> : <Play size={15} />}
                                {isPlaying ? 'Pause' : 'Play Forward'}
                            </button>
                            <button className="btn btn-ghost btn-icon" onClick={() => setReplayIdx(Math.min(history.length - 1, replayIndex + 1))}>
                                <SkipForward size={15} />
                            </button>
                            <button className="btn btn-ghost btn-icon" onClick={() => setReplayIdx(history.length - 1)}>
                                <SkipForward size={15} />
                            </button>
                        </div>
                    </div>

                    {/* Context at replay point */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-5)' }}>
                        <div className="card">
                            <div className="card-header">
                                <span className="card-title-large">Cycle Context — #{replayCycle?.cycle_id}</span>
                                <span className={`badge ${replayCycle?.predictions?.scrap_probability > 0.7 ? 'badge-crit' : replayCycle?.predictions?.scrap_probability > 0.4 ? 'badge-warn' : 'badge-ok'}`}>
                                    {((replayCycle?.predictions?.scrap_probability ?? 0) * 100).toFixed(1)}% Scrap Risk
                                </span>
                            </div>
                            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }}>
                                Data Time: <span style={{ fontFamily: 'JetBrains Mono, monospace' }}>{formatTelemetryTimestamp(replayCycle?.timestamp)}</span>
                            </div>
                            <table className="tele-table">
                                <thead>
                                    <tr>
                                        <th>Parameter</th>
                                        <th>Value</th>
                                        <th>Min</th>
                                        <th>Max</th>
                                        <th>Status</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {Object.entries(replayCycle?.telemetry ?? {}).map(([key, p]) => {
                                        const ok = (p.safe_min === null || p.value >= p.safe_min) && (p.safe_max === null || p.value <= p.safe_max);
                                        return (
                                            <tr key={key}>
                                                <td style={{ color: 'var(--text-secondary)' }}>{PARAM_LABELS[key] ?? key}</td>
                                                <td className="mono" style={{ fontWeight: 700 }}>{p.value}</td>
                                                <td className="mono text-muted">{p.safe_min ?? '—'}</td>
                                                <td className="mono text-muted">{p.safe_max ?? '—'}</td>
                                                <td>
                                                    <span className={`badge ${p.safe_min === null && p.safe_max === null ? 'badge-neutral' : ok ? 'badge-ok' : 'badge-crit'}`} style={{ fontSize: 10 }}>
                                                        {p.safe_min === null && p.safe_max === null ? 'REL' : ok ? 'OK' : 'VIOL'}
                                                    </span>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>

                        <div className="card">
                            <div className="card-header">
                                <span className="card-title-large">SHAP Analysis — Historical Replay</span>
                            </div>
                            <RootCausePanel
                                shap={replayCycle?.shap_attributions}
                                telemetry={replayCycle?.telemetry}
                                scrapProb={replayCycle?.predictions?.scrap_probability ?? 0}
                            />
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
