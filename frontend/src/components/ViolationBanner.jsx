import React from 'react';
import { AlertTriangle, ShieldCheck, ExternalLink, Cog } from 'lucide-react';

export default function ViolationBanner({ violations, machineId }) {
    if (!violations || violations.length === 0) {
        return (
            <div className="alert-banner ok" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <div className="alert-icon">
                        <ShieldCheck color="var(--status-ok)" size={20} />
                    </div>
                    <div className="alert-content">
                        <div className="alert-title" style={{ color: 'var(--status-ok)' }}>PROCESS STABLE — {machineId}</div>
                        <div className="alert-body">All monitored parameters are within safe production boundaries.</div>
                    </div>
                </div>
                <div className="badge badge-ok">HEALTHY</div>
            </div>
        );
    }

    const paramNames = violations.map(v => v.label).join(', ');

    return (
        <div className="alert-banner crit" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div className="alert-icon">
                    <AlertTriangle color="var(--status-crit)" size={24} style={{ animation: 'pulse-crit 1s infinite' }} />
                </div>
                <div className="alert-content">
                    <div className="alert-title" style={{ color: 'var(--status-crit)', fontSize: 14 }}>
                        CRITICAL — {machineId}: {violations.length} PARAMETERS OUT OF RANGE
                    </div>
                    <div className="alert-body">
                        Affected: <strong style={{ color: 'var(--text-primary)' }}>{paramNames}</strong>. Potential scrap production detected.
                    </div>
                </div>
            </div>

            <div className="alert-actions">
                <button className="btn btn-danger btn-sm" onClick={() => window.open('https://jira.example.com/create', '_blank')}>
                    <ExternalLink size={14} /> Create Incident
                </button>
                <button className="btn btn-ghost btn-sm" style={{ border: '1px solid var(--status-crit)' }}>
                    <Cog size={14} /> Calibrate
                </button>
            </div>
        </div>
    );
}
