import { useMemo } from 'react';
import { getTopDefect, buildNarrativeSummary } from '../utils/defectMapper';
import { t } from '../utils/i18n';
import { AlertTriangle, Wrench, TrendingUp, TrendingDown } from 'lucide-react';

const FEATURE_LABELS = {
    cushion: 'Cushion',
    injection_pressure: 'Inj. Pressure',
    holding_pressure: 'Holding Pressure',
    switch_pressure: 'Switch Pressure',
    injection_time: 'Inj. Time',
    dosage_time: 'Dosage Time',
    temp_z1: 'Temp Zone 1',
    temp_z2: 'Temp Zone 2',
    temp_z3: 'Temp Zone 3',
    temp_z4: 'Temp Zone 4',
    temp_z5: 'Temp Zone 5',
    temp_z6: 'Temp Zone 6',
    temp_z7: 'Temp Zone 7',
    temp_z8: 'Temp Zone 8',
};

function formatFeatureLabel(feature) {
    if (!feature) return 'Unknown';
    if (FEATURE_LABELS[feature]) return FEATURE_LABELS[feature];
    const normalized = String(feature)
        .replace(/^temp_z(\d+)$/i, 'temp_zone_$1')
        .replace(/_/g, ' ')
        .trim()
        .toLowerCase();
    return normalized.replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function RootCausePanel({ shap, telemetry, scrapProb }) {
    const sorted = useMemo(() =>
        [...(shap ?? [])].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution)),
        [shap]
    );

    const topDefect = useMemo(() => getTopDefect(sorted), [sorted]);
    const narrative = useMemo(() => buildNarrativeSummary(sorted, telemetry), [sorted, telemetry]);
    const maxAbs = Math.max(...sorted.map(s => Math.abs(s.contribution)), 0.01);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>

            {/* Narrative summary */}
            <div style={{
                padding: '12px 16px',
                background: 'rgba(96,165,250,0.06)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid rgba(96,165,250,0.15)',
                fontSize: 13, lineHeight: 1.6, color: 'var(--text-secondary)',
            }}>
                <span style={{ color: 'var(--accent-blue-lt)', fontWeight: 700 }}>AI Insight: </span>
                {narrative || 'Monitoring within normal parameters.'}
            </div>

            {/* SHAP Waterfall bars */}
            <div>
                <div className="section-title">{t('rootCause')}</div>
                {sorted.map((item) => {
                    const pct = (Math.abs(item.contribution) / maxAbs) * 100;
                    const isPos = item.direction === 'positive';
                    const tele = telemetry?.[item.feature];
                    const val = tele?.value;
                    const set = tele?.setpoint;
                    return (
                        <div key={item.feature} className="shap-row">
                            <div className="shap-feature">
                                {isPos ? <TrendingUp size={12} color="var(--status-crit)" style={{ marginRight: 4, verticalAlign: 'middle' }} />
                                    : <TrendingDown size={12} color="var(--accent-blue-lt)" style={{ marginRight: 4, verticalAlign: 'middle' }} />}
                                {formatFeatureLabel(item.feature)}
                                {val !== undefined && (
                                    <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 1, fontFamily: 'JetBrains Mono, monospace' }}>
                                        {val} {(set !== undefined && set !== null) ? `/ ${set}` : ''}
                                    </div>
                                )}
                            </div>
                            <div className="shap-track">
                                <div className="shap-centerline" />
                                <div
                                    className={`shap-bar ${isPos ? 'pos' : 'neg'}`}
                                    style={{ width: `${pct / 2}%` }}
                                />
                            </div>
                            <div className={`shap-score ${isPos ? 'pos' : 'neg'}`}>
                                {isPos ? '+' : ''}{item.contribution.toFixed(3)}
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* Defect prediction + corrective actions */}
            {topDefect && scrapProb > 0.3 && (
                <div className="defect-banner">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                        <AlertTriangle size={16} color="var(--status-crit)" />
                        <span style={{ fontSize: 13, fontWeight: 800, color: 'var(--status-crit)' }}>
                            Predicted Defect: {topDefect.defect}
                        </span>
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: 8 }}>
                        {topDefect.mechanism}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                        <Wrench size={12} color="var(--status-warn)" />
                        <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--status-warn)' }}>
                            {t('corrective')}
                        </span>
                    </div>
                    <ul className="defect-steps">
                        {topDefect.actions.map((a, i) => <li key={i}>{a}</li>)}
                    </ul>
                    <div style={{ marginTop: 8 }}>
                        <span className="badge badge-neutral" style={{ fontSize: 10 }}>Bucket {topDefect.bucket} Rule</span>
                    </div>
                </div>
            )}
        </div>
    );
}
