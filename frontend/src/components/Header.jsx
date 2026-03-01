import { Cpu, Wifi, Clock } from 'lucide-react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { t } from '../utils/i18n';
import { formatTelemetryTime } from '../utils/time';

const VIEW_LABELS = {
    operator: 'operatorView',
    engineer: 'engineerView',
    manager: 'managerView',
    alerts: 'alertCenter',
    audit: 'auditLog',
};

export default function Header({ activeView }) {
    const latest = useTelemetryStore(s => s.latest);
    const machines = useTelemetryStore(s => s.machines);
    const currentMachine = useTelemetryStore(s => s.currentMachine);
    const partNumber = useTelemetryStore(s => s.partNumber);
    const backendStatus = useTelemetryStore(s => s.backendStatus);
    const backendInfo = useTelemetryStore(s => s.backendInfo);
    const switchMachine = useTelemetryStore(s => s.switchMachine);

    const prob = latest?.predictions?.scrap_probability ?? 0;
    const level = prob >= 0.9 ? 'crit' : prob >= 0.65 ? 'warn' : 'ok';
    const levelColor = { ok: 'var(--status-ok)', warn: 'var(--status-warn)', crit: 'var(--status-crit)' }[level];
    const connectionStyles = {
        online: { label: 'ONLINE', color: 'var(--status-ok)' },
        degraded: { label: 'DEGRADED', color: 'var(--status-warn)' },
        offline: { label: 'OFFLINE', color: 'var(--status-crit)' },
        connecting: { label: 'CONNECTING', color: 'var(--status-info)' },
    };
    const connection = connectionStyles[backendStatus] || connectionStyles.connecting;
    const backendLabel = backendInfo?.backend ? String(backendInfo.backend).toUpperCase() : 'BACKEND';

    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const dateStr = now.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });

    return (
        <header className="top-bar">
            {/* Title */}
            <div style={{ flex: 1 }}>
                <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                    Predictive-Scrap-AI • {dateStr}
                </div>
                <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)', marginTop: 1 }}>
                    {t(VIEW_LABELS[activeView] ?? 'operatorView')}
                </div>
            </div>

            {/* Live cycle indicator */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 12px', background: 'var(--bg-elevated)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-default)' }}>
                <div className="lamp ok" style={{ width: 8, height: 8 }} />
                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)' }}>LIVE</span>
                <span style={{ fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color: 'var(--text-primary)' }}>
                    #{latest?.cycle_id ?? '—'}
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'JetBrains Mono, monospace' }}>
                    {formatTelemetryTime(latest?.timestamp)}
                </span>
            </div>

            {/* Quick scrap indicator */}
            <div style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '6px 14px',
                background: prob >= 0.65 ? `rgba(${level === 'crit' ? '239,68,68' : '245,158,11'},0.12)` : 'var(--bg-elevated)',
                borderRadius: 'var(--radius-md)',
                border: `1px solid ${prob >= 0.65 ? levelColor + '55' : 'var(--border-default)'}`,
                transition: 'all 0.4s',
            }}>
                <Cpu size={14} color={levelColor} />
                <div>
                    <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                        {t('scrapProbability')}
                    </div>
                    <div style={{ fontSize: 16, fontWeight: 900, color: levelColor, lineHeight: 1, fontFamily: 'JetBrains Mono, monospace' }}>
                        {(prob * 100).toFixed(1)}%
                    </div>
                </div>
            </div>

            {/* Machine Selector */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingLeft: 'var(--space-4)', borderLeft: '1px solid var(--border-subtle)' }}>
                <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Machine:</span>
                <select
                    value={currentMachine}
                    onChange={(e) => switchMachine(e.target.value)}
                    style={{
                        background: 'var(--bg-elevated)',
                        border: '1px solid var(--border-default)',
                        borderRadius: 'var(--radius-sm)',
                        padding: '4px 8px',
                        fontSize: 12,
                        fontWeight: 700,
                        color: 'var(--text-primary)',
                        cursor: 'pointer',
                        outline: 'none'
                    }}
                >
                    {(machines.length > 0 ? machines : [{ id: currentMachine }]).map(m => (
                        <option key={m.id} value={m.id}>{m.id}</option>
                    ))}
                </select>
                <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Part:</span>
                <span
                    style={{
                        background: 'var(--bg-elevated)',
                        border: '1px solid var(--border-default)',
                        borderRadius: 'var(--radius-sm)',
                        padding: '4px 8px',
                        fontSize: 12,
                        fontWeight: 700,
                        color: 'var(--text-primary)',
                        fontFamily: 'JetBrains Mono, monospace'
                    }}
                >
                    {partNumber || 'AUTO'}
                </span>
            </div>

            {/* Connection */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, color: 'var(--text-muted)', fontSize: 12 }}>
                <Wifi size={14} color={connection.color} />
                <span style={{ color: connection.color, fontWeight: 700 }}>{backendLabel}</span>
                <span style={{ color: connection.color, fontWeight: 600 }}>{connection.label}</span>
            </div>

            {/* Time */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, color: 'var(--text-secondary)', fontSize: 12 }}>
                <Clock size={13} />
                <span style={{ fontFamily: 'JetBrains Mono, monospace' }}>{timeStr}</span>
            </div>

        </header>
    );
}
