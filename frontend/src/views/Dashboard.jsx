import React, { useEffect, useMemo, useState } from 'react';
import Plot from 'react-plotly.js';
import { useTelemetryStore } from '../store/useTelemetryStore';
import ModelPerformanceDashboard from '../components/ModelPerformanceDashboard';

const HORIZON_OPTIONS = ['1 Hour', '12 Hours', 'Custom'];
const DEFAULT_HISTORY_WINDOW_HOURS = 72;
const LIVE_HORIZON_MAX_HOURS = 32;

function average(values) {
  const valid = (values || []).filter((v) => Number.isFinite(v));
  if (!valid.length) return 0;
  return valid.reduce((sum, value) => sum + value, 0) / valid.length;
}

function formatPercent(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return '0.0%';
  return `${num.toFixed(1)}%`;
}

function formatDeltaPercent(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return '0.0%';
  const sign = num >= 0 ? '+' : '';
  return `${sign}${num.toFixed(1)}%`;
}

function formatDateTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString();
}

export default function Dashboard() {
  const machineId = useTelemetryStore((s) => s.currentMachine);
  const partNumber = useTelemetryStore((s) => s.partNumber);
  const machineRows = useTelemetryStore((s) => s.machines);
  const parts = useTelemetryStore((s) => s.partOptions);
  const switchMachine = useTelemetryStore((s) => s.switchMachine);
  const setPartNumber = useTelemetryStore((s) => s.setPartNumber);
  const chartPayload = useTelemetryStore((s) => s.chartData);
  const chartLoading = useTelemetryStore((s) => s.chartDataLoading);

  const [horizonPreset, setHorizonPreset] = useState('1 Hour');
  const [customHours, setCustomHours] = useState(6);
  const [showFullHistory, setShowFullHistory] = useState(false);
  const [notice, setNotice] = useState('');

  const machines = useMemo(() => (
    Array.isArray(machineRows)
      ? machineRows.map((m) => m?.id).filter(Boolean)
      : []
  ), [machineRows]);

  const horizonHours = useMemo(() => {
    if (horizonPreset === '1 Hour') return 1;
    if (horizonPreset === '12 Hours') return 12;
    return Math.max(1, Number(customHours) || 1);
  }, [customHours, horizonPreset]);

  useEffect(() => {
    if (!machineId) return;
    void useTelemetryStore.getState().loadMachineParts(machineId);
  }, [machineId]);

  useEffect(() => {
    if (!machineId) return;
    const effectiveHorizonHours = Math.max(1, Math.min(horizonHours, LIVE_HORIZON_MAX_HOURS));
    setNotice(
      horizonHours > LIVE_HORIZON_MAX_HOURS
        ? `Forecast horizon capped at ${LIVE_HORIZON_MAX_HOURS} hours.`
        : '',
    );
    void useTelemetryStore.getState().loadChartData(machineId, partNumber, effectiveHorizonHours * 60);
  }, [horizonHours, machineId, partNumber]);

  const chartData = useMemo(() => {
    const past = Array.isArray(chartPayload?.past) ? chartPayload.past : [];
    const future = Array.isArray(chartPayload?.future) ? chartPayload.future : [];
    const meta = chartPayload?.meta || {};
    if (!past.length) return null;

    let displayedPast = past;
    if (!showFullHistory) {
      const latestPastTs = new Date(past[past.length - 1].timestamp).getTime();
      const cutoff = latestPastTs - DEFAULT_HISTORY_WINDOW_HOURS * 60 * 60 * 1000;
      displayedPast = past.filter((row) => new Date(row.timestamp).getTime() >= cutoff);
      if (!displayedPast.length) {
        displayedPast = past.slice(-Math.min(200, past.length));
      }
    }

    const pastX = displayedPast.map((d) => d.timestamp);
    const pastScrap = displayedPast.map((d) => Number(d.scrap_pct || 0));
    const pastVol = displayedPast.map((d) => Number(d.volatility_6pt || 0));

    const seamTs = meta?.past_last_ts || pastX[pastX.length - 1];
    const seamScrap = pastScrap[pastScrap.length - 1] || 0;
    const seamVol = pastVol[pastVol.length - 1] || 0;

    const futureXRaw = future.map((d) => d.timestamp);
    const futureScrapRaw = future.map((d) => Number(d.scrap_pct || 0));
    const futureVolRaw = future.map((d) => Number(d.volatility_6pt || 0));

    return {
      meta,
      pastX,
      pastScrap,
      pastVol,
      futureX: [seamTs, ...futureXRaw],
      futureScrap: [seamScrap, ...futureScrapRaw],
      futureVol: [seamVol, ...futureVolRaw],
      chartStart: pastX[0],
      chartEnd: futureXRaw.length ? futureXRaw[futureXRaw.length - 1] : seamTs,
      seamTs,
      hasFuture: futureXRaw.length > 0,
    };
  }, [chartPayload, showFullHistory]);

  const summary = useMemo(() => {
    const past = Array.isArray(chartPayload?.past) ? chartPayload.past : [];
    const future = Array.isArray(chartPayload?.future) ? chartPayload.future : [];
    if (!past.length) return null;

    const pastRates = past.map((row) => Number(row?.scrap_pct || 0));
    const futureRates = future.map((row) => Number(row?.scrap_pct || 0));
    const pastAvg = average(pastRates);
    const pastLatest = pastRates[pastRates.length - 1] || 0;
    const futureAvg = futureRates.length ? average(futureRates) : 0;

    const futurePeak = future.reduce((best, row) => {
      const score = Number(row?.scrap_pct || 0);
      if (!best || score > best.scrap_pct) return { scrap_pct: score, timestamp: row?.timestamp };
      return best;
    }, null);

    return {
      pastAvg,
      pastLatest,
      futureAvg,
      deltaAvg: futureRates.length ? (futureAvg - pastAvg) : 0,
      futurePeakRate: futurePeak?.scrap_pct || 0,
      futurePeakTs: futurePeak?.timestamp || null,
      hasFuture: futureRates.length > 0,
    };
  }, [chartPayload]);

  return (
    <div style={{ padding: 20, display: 'grid', gap: 16 }}>
      <h2 style={{ margin: 0 }}>Predictive Quality Dashboard</h2>

      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))' }}>
        <label>
          Machine
          <select value={machineId} onChange={(e) => { void switchMachine(e.target.value); }} style={{ width: '100%' }}>
            {(machines.length ? machines : ['M231-11']).map((machine) => (
              <option key={machine} value={machine}>{machine}</option>
            ))}
          </select>
        </label>

        <label>
          Part Number
          <select value={partNumber} onChange={(e) => setPartNumber(e.target.value)} style={{ width: '100%' }} disabled={!parts.length}>
            {parts.length ? parts.map((part) => <option key={part} value={part}>{part}</option>) : <option value="">No parts</option>}
          </select>
        </label>

        <label>
          Prediction Horizon
          <select value={horizonPreset} onChange={(e) => setHorizonPreset(e.target.value)} style={{ width: '100%' }}>
            {HORIZON_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
          </select>
        </label>

        {horizonPreset === 'Custom' && (
          <label>
            Custom Hours
            <input
              type="number"
              min={1}
              max={168}
              step={1}
              value={customHours}
              onChange={(e) => setCustomHours(e.target.value)}
              style={{ width: '100%' }}
            />
          </label>
        )}
      </div>

      <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
        <input
          type="checkbox"
          checked={showFullHistory}
          onChange={(e) => setShowFullHistory(e.target.checked)}
        />
        Show full history (disable for readable near-term view)
      </label>

      {chartLoading && <div>Loading prediction data...</div>}
      {!chartLoading && notice && <div style={{ color: '#8a5200', fontSize: 13 }}>{notice}</div>}
      {!chartLoading && chartData && (
        <div style={{ fontSize: 13, color: '#334155' }}>
          <strong>Reading Guide:</strong> Past = observed machine data. Future = AI forecast.
        </div>
      )}

      {!chartLoading && chartData?.meta && (
        <div style={{ fontSize: 12, color: '#475569', display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <span>Last observed: <strong>{formatDateTime(chartData.meta.past_last_ts)}</strong></span>
          <span>First forecast: <strong>{formatDateTime(chartData.meta.future_first_ts)}</strong></span>
          <span>Ingestion time: <strong>{formatDateTime(chartData.meta.ingestion_time)}</strong></span>
          <span>Forecast horizon capped at 32 hours.</span>
        </div>
      )}

      {!chartLoading && summary && (
        <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))' }}>
          <div className="card" style={{ padding: 12 }}>
            <div style={{ fontSize: 12, color: '#64748b' }}>Past (Latest)</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: '#0B3D91' }}>{formatPercent(summary.pastLatest)}</div>
          </div>
          <div className="card" style={{ padding: 12 }}>
            <div style={{ fontSize: 12, color: '#64748b' }}>Past (Average)</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: '#0B3D91' }}>{formatPercent(summary.pastAvg)}</div>
          </div>
          <div className="card" style={{ padding: 12 }}>
            <div style={{ fontSize: 12, color: '#64748b' }}>Future (Average)</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: '#F97316' }}>
              {summary.hasFuture ? formatPercent(summary.futureAvg) : 'No forecast'}
            </div>
          </div>
          <div className="card" style={{ padding: 12 }}>
            <div style={{ fontSize: 12, color: '#64748b' }}>Future vs Past</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: summary.deltaAvg >= 0 ? '#B91C1C' : '#166534' }}>
              {summary.hasFuture ? formatDeltaPercent(summary.deltaAvg) : '-'}
            </div>
            <div style={{ fontSize: 12, color: '#64748b' }}>
              {summary.hasFuture ? `Peak: ${formatPercent(summary.futurePeakRate)} at ${formatDateTime(summary.futurePeakTs)}` : ''}
            </div>
          </div>
        </div>
      )}

      {!chartLoading && machineId && (
        <div style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid #e2e8f0' }}>
          <h3 style={{ margin: '0 0 16px 0', fontSize: 16, fontWeight: 600 }}>Model Performance</h3>
          <div style={{ background: '#f8fafc', borderLeft: '4px solid #3b82f6', padding: 12, marginBottom: 12, borderRadius: 4 }}>
            <div style={{ fontSize: 12, color: '#475569' }}>
              💡 Model accuracy metrics including precision, recall, F1 score, and confusion matrix for prediction validation
            </div>
          </div>
          <ModelPerformanceDashboard modelId="lightgbm_v1" machineId={machineId} />
        </div>
      )}

      {!chartLoading && chartData && (
        <Plot
          data={[
            {
              x: chartData.pastX,
              y: chartData.pastScrap,
              mode: 'lines',
              name: 'Scrap Probability (Past)',
              line: { color: '#0B3D91', width: 3 },
              yaxis: 'y1',
              customdata: chartData.pastVol,
              hovertemplate: 'Segment: Past<br>%{x|%d %b %Y %H:%M}<br>Scrap: %{y:.2f}%<br>Volatility (6-pt): %{customdata:.3f}<extra></extra>',
            },
            {
              x: chartData.futureX,
              y: chartData.futureScrap,
              mode: 'lines',
              name: 'Scrap Probability (Forecast)',
              line: { color: '#F97316', width: 3, dash: 'dash' },
              yaxis: 'y1',
              customdata: chartData.futureVol,
              hovertemplate: 'Segment: Future<br>%{x|%d %b %Y %H:%M}<br>Scrap: %{y:.2f}%<br>Volatility (6-pt): %{customdata:.3f}<br>Model label: forecasted<extra></extra>',
            },
            {
              x: chartData.pastX,
              y: chartData.pastVol,
              mode: 'lines',
              name: 'Volatility (Past)',
              line: { color: '#DC2626', width: 2 },
              yaxis: 'y2',
              hovertemplate: 'Segment: Past<br>%{x|%d %b %Y %H:%M}<br>Volatility (6-pt): %{y:.3f}<extra></extra>',
            },
            {
              x: chartData.futureX,
              y: chartData.futureVol,
              mode: 'lines',
              name: 'Volatility (Forecast)',
              line: { color: '#DC2626', width: 2, dash: 'dash' },
              yaxis: 'y2',
              hovertemplate: 'Segment: Future<br>%{x|%d %b %Y %H:%M}<br>Volatility (6-pt): %{y:.3f}<extra></extra>',
            },
          ]}
          layout={{
            title: `${machineId} | Part ${partNumber || 'AUTO'}`,
            autosize: true,
            hovermode: 'x unified',
            legend: { orientation: 'h', y: -0.2 },
            xaxis: { title: 'Time', type: 'date', range: [chartData.chartStart, chartData.chartEnd] },
            yaxis: { title: 'Scrap Probability (%)', range: [0, 100] },
            yaxis2: { title: 'Parameter Volatility', overlaying: 'y', side: 'right', range: [0, Math.max(1, ...chartData.pastVol, ...chartData.futureVol)] },
            shapes: [
              {
                type: 'rect',
                xref: 'x',
                yref: 'paper',
                x0: chartData.chartStart,
                x1: chartData.seamTs,
                y0: 0,
                y1: 1,
                fillcolor: 'rgba(11,61,145,0.06)',
                line: { width: 0 },
                layer: 'below',
              },
              {
                type: 'rect',
                xref: 'x',
                yref: 'paper',
                x0: chartData.seamTs,
                x1: chartData.chartEnd,
                y0: 0,
                y1: 1,
                fillcolor: 'rgba(249,115,22,0.06)',
                line: { width: 0 },
                layer: 'below',
              },
              {
                type: 'line',
                x0: chartData.seamTs,
                x1: chartData.seamTs,
                y0: 0,
                y1: 1,
                yref: 'paper',
                line: { color: '#DC2626', width: 3, dash: 'dot' },
              },
            ],
            annotations: [
              {
                x: chartData.seamTs,
                y: 1.06,
                yref: 'paper',
                text: `Past -> Future seam`,
                showarrow: false,
                font: { color: '#991B1B', size: 12 },
              },
            ],
            margin: { t: 60, r: 60, b: 70, l: 60 },
          }}
          style={{ width: '100%', height: '520px' }}
          config={{ responsive: true, displaylogo: false }}
        />
      )}
    </div>
  );
}
