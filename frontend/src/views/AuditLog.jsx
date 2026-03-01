import { useTelemetryStore } from '../store/useTelemetryStore';
import { Activity, ShieldCheck, User, Zap } from 'lucide-react';

export default function AuditLog() {
    const auditLog = useTelemetryStore(s => s.auditLog);

    const getIcon = (actor) => {
        if (actor === 'AI') return <Zap size={14} color="var(--accent-blue-lt)" />;
        if (actor === 'ENG-02') return <ShieldCheck size={14} color="var(--status-ok)" />;
        return <User size={14} color="var(--text-secondary)" />;
    };

    return (
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 0, padding: 0 }}>
            <div className="card-header" style={{ padding: 'var(--space-4) var(--space-5)', borderBottom: '1px solid var(--border-subtle)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <Activity size={18} color="var(--accent-blue-lt)" />
                    <span className="card-title-large">System Operation Audit Log</span>
                </div>
                <span className="badge badge-neutral">Immutable Trail</span>
            </div>

            <div style={{ maxHeight: '70vh', overflowY: 'auto', padding: '0 var(--space-5)' }}>
                {auditLog.map((entry) => (
                    <div key={entry.id} className="audit-entry">
                        <div className="audit-ts">{entry.ts}</div>
                        <div className="audit-actor" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            {getIcon(entry.actor)}
                            {entry.actor}
                        </div>
                        <div className="audit-msg">{entry.msg}</div>
                    </div>
                ))}

                {auditLog.length === 0 && (
                    <div style={{ padding: 'var(--space-8)', textAlign: 'center', color: 'var(--text-muted)' }}>
                        No audit events recorded yet.
                    </div>
                )}
            </div>

            <div style={{ padding: 'var(--space-4) var(--space-5)', background: 'rgba(255,255,255,0.02)', borderTop: '1px solid var(--border-subtle)', fontSize: 11, color: 'var(--text-muted)' }}>
                Generated for Maharashtra Industrial Development Corporation (MIDC) Compliance.
            </div>
        </div>
    );
}
