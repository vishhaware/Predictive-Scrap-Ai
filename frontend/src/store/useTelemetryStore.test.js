import test from 'node:test';
import assert from 'node:assert/strict';
import { useTelemetryStore } from './useTelemetryStore.js';

test('bootstrap loads once and deduplicates repeated calls', async () => {
    const calls = [];
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async (url) => {
        calls.push(String(url));

        if (String(url).endsWith('/api/health')) {
            return {
                ok: true,
                async json() {
                    return { ok: true, backend: 'fastapi' };
                }
            };
        }

        if (String(url).endsWith('/api/machines')) {
            return {
                ok: true,
                async json() {
                    return [
                        { id: 'M231-11', name: 'M231-11', oee: 90, scraps: 0, status: 'ok', temp: 230, cycles: 1 }
                    ];
                }
            };
        }

        if (String(url).includes('/api/machines/M231-11/cycles')) {
            return {
                ok: true,
                async json() {
                    return [{
                        cycle_id: '1',
                        timestamp: '2026-01-01T00:00:00.000Z',
                        telemetry: { cushion: { value: 1.2, safe_min: 1.0, safe_max: 1.4 } },
                        predictions: { scrap_probability: 0.1, confidence: 0.95, risk_level: 'NORMAL', primary_defect_risk: 'None' },
                        shap_attributions: []
                    }];
                }
            };
        }

        if (String(url).includes('/api/machines/M231-11/parts')) {
            return {
                ok: true,
                async json() {
                    return {
                        machine_id: 'M231-11',
                        parts: [
                            { part_number: '8-1419168-4', events: 10 },
                            { part_number: '1411223-1', events: 8 },
                        ],
                    };
                }
            };
        }

        if (String(url).includes('/api/machines/M231-11/control-room')) {
            return {
                ok: true,
                async json() {
                    return {
                        machine_id: 'M231-11',
                        part_number: '8-1419168-4',
                        root_causes: [],
                        future_summary: { peak_scrap_probability: 0.12, predicted_scrap_events: 0 },
                        future_timeline: [],
                    };
                }
            };
        }

        if (String(url).includes('/api/machines/M231-11/chart-data')) {
            return {
                ok: true,
                async json() {
                    return {
                        machine_id: 'M231-11',
                        part_number: '8-1419168-4',
                        past: [
                            {
                                timestamp: '2026-01-01T00:00:00.000Z',
                                scrap_prob: 0.1,
                                scrap_pct: 10,
                                volatility_6pt: 0,
                                segment: 'Past',
                                source: 'observed',
                            },
                        ],
                        future: [
                            {
                                timestamp: '2026-01-01T00:01:00.000Z',
                                scrap_prob: 0.2,
                                scrap_pct: 20,
                                volatility_6pt: 1,
                                segment: 'Future',
                                source: 'forecasted',
                            },
                        ],
                        meta: {
                            past_last_ts: '2026-01-01T00:00:00.000Z',
                            future_first_ts: '2026-01-01T00:01:00.000Z',
                            seam_ok: true,
                        },
                    };
                }
            };
        }

        if (String(url).includes('/api/fleet/chart-data')) {
            return {
                ok: true,
                async json() {
                    return {
                        past: [],
                        future: [],
                        per_machine: [],
                        meta: { seam_ok: true },
                    };
                }
            };
        }

        if (String(url).includes('/api/ai/metrics')) {
            return {
                ok: true,
                async json() {
                    return {
                        generated_at: '2026-02-26T00:00:00.000Z',
                        machine_scope: ['M231-11'],
                        window_cycles: 600,
                        risk_threshold: 0.6,
                        lead_window_cycles: 30,
                        fleet_metrics: {
                            labeled_samples: 1,
                            observed_scrap_events: 0,
                            avg_confidence: 0.95,
                            lead_alert_coverage: 1.0,
                            brier_score: 0.02,
                        },
                        per_machine: [],
                    };
                }
            };
        }

        throw new Error(`Unexpected fetch URL: ${url}`);
    };

    try {
        await Promise.all([
            useTelemetryStore.getState().bootstrap(),
            useTelemetryStore.getState().bootstrap()
        ]);
        await useTelemetryStore.getState().bootstrap();

        assert.equal(calls.filter(x => x.endsWith('/api/machines')).length, 1);
        assert.equal(calls.filter(x => x.includes('/api/machines/M231-11/cycles')).length, 1);
        assert.equal(calls.filter(x => x.includes('/api/machines/M231-11/chart-data')).length, 1);
        assert.equal(calls.filter(x => x.includes('/api/fleet/chart-data')).length, 1);
        assert.equal(calls.filter(x => x.endsWith('/api/health')).length, 1);
        assert.equal(calls.filter(x => x.includes('/api/ai/metrics')).length, 1);

        const state = useTelemetryStore.getState();
        assert.equal(state.machines.length, 1);
        assert.equal(state.history.length, 1);
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test('loadChartData stores machine past/future payload', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url) => {
        if (!String(url).includes('/api/machines/M231-11/chart-data')) {
            throw new Error(`Unexpected fetch URL: ${url}`);
        }
        return {
            ok: true,
            async json() {
                return {
                    machine_id: 'M231-11',
                    past: [{ timestamp: '2026-01-01T00:00:00.000Z', scrap_prob: 0.1, scrap_pct: 10, volatility_6pt: 0, segment: 'Past', source: 'observed' }],
                    future: [{ timestamp: '2026-01-01T00:01:00.000Z', scrap_prob: 0.2, scrap_pct: 20, volatility_6pt: 1, segment: 'Future', source: 'forecasted' }],
                    meta: { seam_ok: true },
                };
            },
        };
    };

    try {
        await useTelemetryStore.getState().loadChartData('M231-11', '8-1419168-4', 120);
        const state = useTelemetryStore.getState();
        assert.equal(Boolean(state.chartData), true);
        assert.equal(state.chartData.meta.seam_ok, true);
        assert.equal(state.chartData.past.length, 1);
        assert.equal(state.chartData.future.length, 1);
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test('loadFleetChartData stores aggregated payload', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url) => {
        if (!String(url).includes('/api/fleet/chart-data')) {
            throw new Error(`Unexpected fetch URL: ${url}`);
        }
        return {
            ok: true,
            async json() {
                return {
                    past: [{ timestamp: '2026-01-01T00:00:00.000Z', scrap_prob: 0.1, scrap_pct: 10, volatility_6pt: 0, segment: 'Past', source: 'fleet_observed' }],
                    future: [{ timestamp: '2026-01-01T00:05:00.000Z', scrap_prob: 0.2, scrap_pct: 20, volatility_6pt: 1, segment: 'Future', source: 'fleet_forecasted' }],
                    per_machine: [{ machine_id: 'M231-11', future_peak_scrap_prob: 0.2 }],
                    meta: { seam_ok: true },
                };
            },
        };
    };

    try {
        await useTelemetryStore.getState().loadFleetChartData(120);
        const state = useTelemetryStore.getState();
        assert.equal(Boolean(state.fleetChartData), true);
        assert.equal(state.fleetChartData.meta.seam_ok, true);
        assert.equal(state.fleetChartData.per_machine.length, 1);
    } finally {
        globalThis.fetch = originalFetch;
    }
});
