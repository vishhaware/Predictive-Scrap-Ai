import { useTelemetryStore } from '../store/useTelemetryStore';
import AlertBanner from '../components/AlertBanner';
import { Bell, CheckCircle, Trash2, AlertTriangle } from 'lucide-react';

export default function AlertCenter({ onNav }) {
    const alerts = useTelemetryStore(s => s.alerts);
    const dismissAlert = useTelemetryStore(s => s.dismissAlert);
    const machines = useTelemetryStore(s => s.machines);

    const active = alerts.filter(a => !a.acked);
    const history = alerts.filter(a => a.acked);

    // Generate passive alerts from machine summary data
    const machineAlerts = (machines || [])
        .filter(m => m.status === 'crit' || m.status === 'warn')
        .map(m => ({
            id: `machine-${m.id}`,
            level: m.status === 'crit' ? 'crit' : 'warn',
            title: `${m.id} — ${m.status === 'crit' ? 'CRITICAL' : 'WARNING'}: OEE ${m.oee}%`,
            body: m.abnormal_params && m.abnormal_params.length > 0
                ? `Abnormal parameters: ${m.abnormal_params.join(', ')}. Maintenance urgency: ${m.maintenance_urgency || 'LOW'}.`
                : `Machine requires attention. Maintenance urgency: ${m.maintenance_urgency || 'LOW'}.`,
            ts: new Date().toLocaleTimeString(),
            acked: false,
            isPassive: true,
        }));

    const allActive = [...active, ...machineAlerts];

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
            {/* Active Alerts */}
            <section>
                <div className="section-title" style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 'var(--space-4)' }}>
                    <Bell size={14} color="var(--status-crit)" />
                    Active Alerts ({allActive.length})
                </div>

                {allActive.length === 0 ? (
                    <div className="card" style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--text-muted)' }}>
                        {machines.every(m => m.status === 'unknown')
                            ? "System is currently initializing. Machine status will appear shortly..."
                            : "All systems nominal. No active alerts."}
                    </div>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                        {allActive.map(a => a.isPassive ? (
                            <div key={a.id} className="card" style={{
                                padding: '14px 18px',
                                borderLeft: `4px solid ${a.level === 'crit' ? 'var(--status-crit)' : 'var(--status-warn)'}`,
                                background: a.level === 'crit' ? 'var(--status-crit-dim)' : 'var(--status-warn-dim)',
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                                    <AlertTriangle size={14} color={a.level === 'crit' ? 'var(--status-crit)' : 'var(--status-warn)'} />
                                    <span style={{ fontWeight: 700, fontSize: 13, color: a.level === 'crit' ? 'var(--status-crit)' : 'var(--status-warn)' }}>
                                        {a.title}
                                    </span>
                                    <span className={`badge ${a.level === 'crit' ? 'badge-crit' : 'badge-warn'}`} style={{ marginLeft: 'auto', fontSize: 10 }}>
                                        MACHINE STATUS
                                    </span>
                                </div>
                                <div style={{ fontSize: 12, color: 'var(--text-secondary)', paddingLeft: 22 }}>
                                    {a.body}
                                </div>
                            </div>
                        ) : (
                            <AlertBanner key={a.id} alert={a} onNav={onNav} />
                        ))}
                    </div>
                )}
            </section>

            {/* Alert History */}
            <section>
                <div className="section-title" style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 'var(--space-4)' }}>
                    <CheckCircle size={14} color="var(--text-muted)" />
                    Resolved / Acknowledged
                </div>

                {history.length === 0 ? (
                    <div style={{ padding: 'var(--space-4)', fontSize: 13, color: 'var(--text-muted)', fontStyle: 'italic' }}>
                        No historical alerts in this session.
                    </div>
                ) : (
                    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                        <table className="tele-table">
                            <thead>
                                <tr>
                                    <th>Timestamp</th>
                                    <th>Alert Title</th>
                                    <th>Cycle</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {history.map(a => (
                                    <tr key={a.id}>
                                        <td className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>{a.ts}</td>
                                        <td style={{ fontWeight: 600, color: a.level === 'crit' ? 'var(--status-crit)' : 'var(--status-warn)' }}>{a.title}</td>
                                        <td className="mono">#{a.cycle}</td>
                                        <td>
                                            <button
                                                className="btn btn-ghost btn-sm btn-icon"
                                                onClick={() => dismissAlert(a.id)}
                                                title="Remove from history"
                                            >
                                                <Trash2 size={13} />
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </section>
        </div>
    );
}
