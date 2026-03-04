import React from 'react';
import { Activity, Factory, LayoutDashboard, Settings, Bell } from 'lucide-react';
import { useTelemetryStore } from '../store/useTelemetryStore';

const NAV_ITEMS = [
    { id: 'operator', icon: LayoutDashboard, label: 'Process Dashboard' },
    { id: 'manager', icon: Factory, label: 'Plant Manager' },
    { id: 'alerts', icon: Bell, label: 'Alert Center' },
    { id: 'audit', icon: Activity, label: 'Audit Log' },
];

export default function Sidebar({ activeView, onNav }) {
    const alertCount = useTelemetryStore(s => s.alertCount);

    return (
        <aside className="sidebar">
            {/* Logo */}
            <div className="nav-logo">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                    <path d="M12 2L2 7l10 5 10-5-10-5z" stroke="#fff" strokeWidth="2" strokeLinejoin="round" />
                    <path d="M2 17l10 5 10-5" stroke="#fff" strokeWidth="2" strokeLinejoin="round" />
                    <path d="M2 12l10 5 10-5" stroke="#fff" strokeWidth="2" strokeLinejoin="round" />
                </svg>
            </div>

            {NAV_ITEMS.map(({ id, icon, label }) => (
                <button
                    key={id}
                    className={`nav-item${activeView === id ? ' active' : ''}`}
                    onClick={() => onNav(id)}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', position: 'relative' }}
                >
                    {React.createElement(icon, { size: 19 })}
                    {id === 'alerts' && alertCount > 0 && (
                        <span style={{
                            position: 'absolute', top: 6, right: 6,
                            background: 'var(--status-crit)', color: '#fff',
                            fontSize: 9, fontWeight: 800,
                            width: 16, height: 16, borderRadius: '50%',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            border: '2px solid var(--bg-surface)',
                            lineHeight: 1,
                        }}>{alertCount > 9 ? '9+' : alertCount}</span>
                    )}
                    <span className="tooltip">{label}</span>
                </button>
            ))}

            <div className="nav-spacer" />

            <button className="nav-item" style={{ background: 'none', border: 'none', cursor: 'pointer' }}>
                <Settings size={19} />
                <span className="tooltip">Settings</span>
            </button>
        </aside>
    );
}
