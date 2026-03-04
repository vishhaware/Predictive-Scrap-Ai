import { useState, useMemo, useEffect } from 'react';
import { Download } from 'lucide-react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import RangeAreaChart from '../components/RangeAreaChart';
import RelationalScatterPlot from '../components/RelationalScatterPlot';
import RootCausePanel from '../components/RootCausePanel';
import ViolationBanner from '../components/ViolationBanner';

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
export default function EngineerView() {
    const history = useTelemetryStore(s => s.history);
    const latest = useTelemetryStore(s => s.latest);
    const currentMachine = useTelemetryStore(s => s.currentMachine);
    const partNumber = useTelemetryStore(s => s.partNumber);
    const controlRoom = useTelemetryStore(s => s.controlRoom);
    const chartData = useTelemetryStore(s => s.chartData);

    const [activeTab, setActiveTab] = useState('telemetry');
    const [isExporting, setIsExporting] = useState(false);

    useEffect(() => {
        if (!currentMachine) return;
        void useTelemetryStore.getState().loadControlRoom(currentMachine, partNumber);
    }, [currentMachine, partNumber]);

    const handleExport = async () => {
        setIsExporting(true);
        try {
            const resp = await fetch('/api/admin/export-validation', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            let payload = null;
            try {
                payload = await resp.json();
            } catch {
                payload = null;
            }

            const errorMessage =
                payload?.error ||
                payload?.detail ||
                payload?.message ||
                `HTTP ${resp.status}`;

            if (resp.ok && payload?.ok) {
                const artifacts = [
                    payload?.validation_workbook ? `Workbook: ${payload.validation_workbook}` : null,
                    payload?.live_check_csv ? `Live CSV: ${payload.live_check_csv}` : null,
                    payload?.backtest_csv ? `Backtest CSV: ${payload.backtest_csv}` : null,
                ].filter(Boolean);
                alert(`Success! Validation artifacts generated.\n${artifacts.join('\n')}`);
            } else {
                alert('Export failed: ' + errorMessage);
            }
        } catch (err) {
            alert('Export error: ' + err.message);
        } finally {
            setIsExporting(false);
        }
    };

    const telemetryParams = useMemo(() => {
        const latestTelemetry = latest?.telemetry || {};
        const available = Object.keys(latestTelemetry);
        const ordered = PREFERRED_PARAMS.filter((param) => available.includes(param));
        const fallback = available
            .filter((param) => !ordered.includes(param))
            .slice(0, 8 - ordered.length);
        return [...ordered, ...fallback].slice(0, 8);
    }, [latest]);

    const violations = useMemo(() => {
        const tele = latest?.telemetry || {};
        return Object.entries(tele)
            .filter(([_, p]) => {
                const ok = (p.safe_min === null || p.value >= p.safe_min) && (p.safe_max === null || p.value <= p.safe_max);
                return !ok;
            })
            .map(([k, _]) => ({ key: k, label: k.replace(/_/g, ' ').toUpperCase() }));
    }, [latest]);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>

            <ViolationBanner violations={violations} machineId={currentMachine} />

            {/* Tab selector */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div className="tabs">
                    {[
                        { id: 'telemetry', label: 'Multi-Param Telemetry' },
                        { id: 'relational', label: 'Relational Plot' },
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

                <button
                    className="btn btn-primary btn-sm"
                    onClick={handleExport}
                    disabled={isExporting}
                    style={{ gap: 8 }}
                >
                    <Download size={14} /> {isExporting ? 'Processing...' : 'Export Excel Validation'}
                </button>
            </div>

            {/* ── TELEMETRY GRID ── */}
            {chartData?.meta && (
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: -4 }}>
                    Past -&gt; Future seam — last observed: {chartData.meta.past_last_ts ? new Date(chartData.meta.past_last_ts).toLocaleString() : 'N/A'} · first forecast: {chartData.meta.future_first_ts ? new Date(chartData.meta.future_first_ts).toLocaleString() : 'N/A'}
                </div>
            )}
            {activeTab === 'telemetry' && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 'var(--space-4)' }}>
                    {telemetryParams.map(param => (
                        <div key={param} className="card">
                            <RangeAreaChart history={history} forecast={controlRoom?.future_timeline} param={param} windowSize={80} />
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
        </div>
    );
}
