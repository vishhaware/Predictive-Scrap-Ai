import { AlertTriangle, XCircle, CheckCircle, Info, X, Zap, Eye } from 'lucide-react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { t } from '../utils/i18n';

const ICONS = {
    crit: <XCircle size={20} color="var(--status-crit)" />,
    warn: <AlertTriangle size={20} color="var(--status-warn)" />,
    ok: <CheckCircle size={20} color="var(--status-ok)" />,
    info: <Info size={20} color="var(--status-info)" />,
};

export default function AlertBanner({ alert, onNav }) {
    const ackAlert = useTelemetryStore(s => s.ackAlert);
    const dismissAlert = useTelemetryStore(s => s.dismissAlert);
    const logAudit = useTelemetryStore(s => s.logAudit);

    if (!alert || alert.acked) return null;

    function handleAck() {
        ackAlert(alert.id);
        logAudit({ actor: 'OPR-??', msg: `Acknowledged alert — ${alert.title}` });
    }

    function handleEStop() {
        dismissAlert(alert.id);
        logAudit({ actor: 'OPR-??', msg: `E-STOP initiated after alert — ${alert.title}` });
    }

    return (
        <div className={`alert-banner ${alert.level}`} role="alert">
            <div className="alert-icon">{ICONS[alert.level] ?? ICONS.info}</div>

            <div className="alert-content">
                <div className="alert-title" style={{ color: alert.level === 'crit' ? 'var(--status-crit)' : alert.level === 'warn' ? 'var(--status-warn)' : 'var(--text-primary)' }}>
                    {alert.level === 'crit' && <Zap size={13} style={{ display: 'inline', marginRight: 4, verticalAlign: 'middle' }} />}
                    {alert.title}
                </div>
                <div className="alert-body">{alert.body}</div>
                <div style={{ marginTop: 4, fontSize: 10, color: 'var(--text-muted)', fontFamily: 'JetBrains Mono, monospace' }}>
                    Cycle #{alert.cycle} • {alert.ts}
                </div>
            </div>

            <div className="alert-actions">
                <button className="btn btn-ghost btn-sm" onClick={() => onNav?.('engineer')}>
                    <Eye size={13} />{t('viewDiagnostics')}
                </button>
                <button className="btn btn-warn btn-sm" onClick={handleAck}>
                    <CheckCircle size={13} />{t('acknowledge')}
                </button>
                {alert.level === 'crit' && (
                    <button className="btn btn-danger btn-sm" onClick={handleEStop}>
                        <XCircle size={13} />{t('eStop')}
                    </button>
                )}
                <button
                    onClick={() => dismissAlert(alert.id)}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', padding: 4 }}
                >
                    <X size={15} />
                </button>
            </div>
        </div>
    );
}
