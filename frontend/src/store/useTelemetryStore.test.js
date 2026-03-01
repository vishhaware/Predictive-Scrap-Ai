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
        assert.equal(calls.filter(x => x.endsWith('/api/health')).length, 1);
        assert.equal(calls.filter(x => x.includes('/api/ai/metrics')).length, 1);

        const state = useTelemetryStore.getState();
        assert.equal(state.machines.length, 1);
        assert.equal(state.history.length, 1);
    } finally {
        globalThis.fetch = originalFetch;
    }
});
