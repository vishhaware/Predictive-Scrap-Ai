const test = require('node:test');
const assert = require('node:assert/strict');
const { DriftTracker, analyzeShotSequence } = require('../engine');

function makeShot(index, overrides = {}) {
    return {
        _timestamp: new Date(Date.UTC(2026, 0, 1, 0, 0, index)).toISOString(),
        Cushion: 1.2,
        Injection_time: 0.6,
        Dosage_time: 3.2,
        Injection_pressure: 1200,
        Switch_pressure: 900,
        Cycle_time: 18.0,
        Cyl_tmp_z1: 230,
        Cyl_tmp_z2: 231,
        Cyl_tmp_z3: 232,
        Cyl_tmp_z4: 233,
        Cyl_tmp_z5: 234,
        ...overrides
    };
}

test('engine returns predictions for baseline shots', () => {
    const shots = Array.from({ length: 60 }, (_, i) => makeShot(i));
    const analyzed = analyzeShotSequence(shots, new DriftTracker());

    assert.equal(analyzed.length, 60);
    assert.ok(analyzed[0].predictions);
    assert.ok(typeof analyzed[0].predictions.scrap_probability === 'number');
    assert.ok(typeof analyzed[0].predictions.confidence === 'number');
    assert.equal(analyzed[0].predictions.model_label, 'XGBoost v3.1');
    assert.ok(analyzed[0].telemetry.cushion);
});

test('engine marks low cushion shots as certain risk', () => {
    const baseline = Array.from({ length: 60 }, (_, i) => makeShot(i));
    const anomaly = makeShot(61, { Cushion: 0.1 });
    const analyzed = analyzeShotSequence([...baseline, anomaly], new DriftTracker());
    const last = analyzed[analyzed.length - 1];

    assert.equal(last.predictions.risk_level, 'CERTAIN');
    assert.ok(last.predictions.scrap_probability >= 0.9);
    assert.ok(last.predictions.confidence >= 0.95);
});
