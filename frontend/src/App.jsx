import React, { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import PredictiveDashboard from './views/Dashboard';
import EngineerView from './views/EngineerView';
import ManagerView from './views/ManagerView';
import AlertCenter from './views/AlertCenter';
import AuditLog from './views/AuditLog';
import { useMockWebSocket } from './hooks/useMockWebSocket';
import { useTelemetryStore } from './store/useTelemetryStore';

function App() {
  const [activeView, setActiveView] = useState('operator');
  const isLoading = useTelemetryStore(s => s.isLoading);
  const history = useTelemetryStore(s => s.history);
  const backendInfo = useTelemetryStore(s => s.backendInfo);

  // Connect to real backend WebSocket
  useMockWebSocket();

  // Load real data from backend on startup
  useEffect(() => {
    void useTelemetryStore.getState().bootstrap();
    let monitorInFlight = false;

    const monitor = setInterval(async () => {
      if (monitorInFlight) return;
      monitorInFlight = true;
      try {
        const state = useTelemetryStore.getState();
        const health = await state.checkBackendHealth();
        if (!health) return;

        const now = Date.now();
        const machinesStale = now - (state.lastMachinesRefreshAt || 0) > 30000;
        const cyclesStale = now - (state.lastCyclesRefreshAt || 0) > 25000;
        const controlRoomStale = now - (state.lastControlRoomRefreshAt || 0) > 90000;
        const chartDataStale = now - (state.lastChartDataRefreshAt || 0) > 60000;
        const fleetChartStale = now - (state.lastFleetChartDataRefreshAt || 0) > 90000;
        const aiMetricsStale = now - (state.lastAiMetricsRefreshAt || 0) > 120000;

        if (machinesStale) {
          await state.loadMachines();
        }

        // If backend came back or WS paused, rehydrate current machine data.
        if ((!state.isLoading && state.history.length === 0) || cyclesStale) {
          await state.loadCycles(state.currentMachine);
        }

        if (state.partOptions.length === 0) {
          await state.loadMachineParts(state.currentMachine);
        }

        if (controlRoomStale || !state.controlRoom) {
          await state.loadControlRoom(state.currentMachine, state.partNumber);
        }

        if (chartDataStale || !state.chartData) {
          const activeHorizon = Number(state.chartData?.meta?.horizon_used_minutes || 60);
          await state.loadChartData(state.currentMachine, state.partNumber, activeHorizon);
        }

        if (fleetChartStale || !state.fleetChartData) {
          await state.loadFleetChartData(60);
        }

        if (aiMetricsStale || !state.aiMetrics) {
          await state.loadAiMetrics();
        }
      } finally {
        monitorInFlight = false;
      }
    }, 10000);

    return () => clearInterval(monitor);
  }, []);

  const handleNav = (viewId) => {
    setActiveView(viewId);
  };

  const renderView = () => {
    switch (activeView) {
      case 'operator':
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
            <EngineerView />
            <PredictiveDashboard />
          </div>
        );
      case 'engineer': return <EngineerView />;
      case 'manager': return <ManagerView />;
      case 'alerts': return <AlertCenter onNav={handleNav} />;
      case 'audit': return <AuditLog />;
      default:
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
            <EngineerView />
            <PredictiveDashboard />
          </div>
        );
    }
  };

  return (
    <div className="app-shell">
      {/* Left Navigation */}
      <Sidebar activeView={activeView} onNav={handleNav} />

      {/* Main Container */}
      <div className="main-area">
        {/* Top bar with state indicators */}
        <Header activeView={activeView} />

        {/* Scrollable Content */}
        <main className="content-area">
          {isLoading && history.length === 0 ? (
            <div style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
              flex: 1, gap: 16, color: 'var(--text-muted)'
            }}>
              <div className="lamp ok" style={{ width: 20, height: 20 }} />
              <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-secondary)' }}>
                Loading Telemetry Data...
              </div>
              <div style={{ fontSize: 12 }}>
                Processing CSV files through the 4-Layer Prediction Engine
              </div>
            </div>
          ) : renderView()}

          {/* Footer / Status bar */}
          <footer style={{ marginTop: 'auto', padding: '20px 0 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--border-subtle)', fontSize: 11, color: 'var(--text-muted)' }}>
            <div>Smart Factory Brain v2.0 | 4-Layer Prediction Engine | {history.length} cycles loaded</div>
            <div style={{ display: 'flex', gap: 12 }}>
              <span>
                System Health: {backendInfo?.ok ? 'OK' : 'DEGRADED'}
              </span>
              <span>
                DB: {backendInfo?.db_status || 'unknown'} | Data: {backendInfo?.data_status || 'unknown'} | Ingestion: {backendInfo?.ingestion_status || 'unknown'}
              </span>
            </div>
          </footer>
        </main>
      </div>
    </div>
  );
}

export default App;
