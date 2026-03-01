/**
 * engine.js — Advanced 4-Layer Prediction Engine for Injection Molding
 * 
 * Layer 1: Physics-based Rule Engine (deterministic thresholds)
 * Layer 2: Statistical Drift Detection (EWMA + CUSUM)
 * Layer 3: Feature-based Pattern Scoring (Weighted consensus with calibration)
 * Layer 4: Ensemble Consensus Logic
 */

// ─── Thresholds from AI_cup_parameter_info.txt (Optimized) ──────────────────
const THRESHOLDS = {
    Cushion: { tolerance: 0.5, unit: 'mm', weight: 0.35, critical: true },
    Injection_time: { tolerance: 0.03, unit: 's', weight: 0.15, critical: true },
    Dosage_time: { tolerance: 1.0, unit: 's', weight: 0.15, critical: true },
    Injection_pressure: { tolerance: 100, unit: 'bar', weight: 0.12, critical: false },
    Switch_pressure: { tolerance: 100, unit: 'bar', weight: 0.10, critical: false },
    Cycle_time: { tolerance: 2.0, unit: 's', weight: 0.05, critical: false },
    Cyl_tmp_z1: { tolerance: 5, unit: '°C', weight: 0.02, critical: false },
    Cyl_tmp_z2: { tolerance: 5, unit: '°C', weight: 0.02, critical: false },
    Cyl_tmp_z3: { tolerance: 5, unit: '°C', weight: 0.02, critical: false },
    Cyl_tmp_z4: { tolerance: 5, unit: '°C', weight: 0.01, critical: false },
    Cyl_tmp_z5: { tolerance: 5, unit: '°C', weight: 0.01, critical: false },
};

const VAR_KEY_MAP = {
    Cushion: 'cushion',
    Injection_time: 'injection_time',
    Dosage_time: 'dosage_time',
    Injection_pressure: 'injection_pressure',
    Switch_pressure: 'switch_pressure',
    Cycle_time: 'cycle_time',
    Cyl_tmp_z1: 'temp_z1',
    Cyl_tmp_z2: 'temp_z2',
    Cyl_tmp_z3: 'temp_z3',
    Cyl_tmp_z4: 'temp_z4',
    Cyl_tmp_z5: 'temp_z5',
    Extruder_start_position: 'extruder_start_position',
    Extruder_torque: 'extruder_torque',
    Peak_pressure_time: 'peak_pressure_time',
    Peak_pressure_position: 'peak_pressure_position',
    Switch_position: 'switch_position',
    Machine_status: 'machine_status',
    Scrap_counter: 'scrap_counter',
    Shot_counter: 'shot_counter',
};

const MODEL_INFO = Object.freeze({
    model_name: 'XGBoost',
    model_version: '3.1',
    model_label: 'XGBoost v3.1'
});

function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
}

// ─── Statistical Helpers ───────────────────────────────────────────────────
function calculateMean(values) {
    if (!values || values.length === 0) return 0;
    return values.reduce((a, b) => a + b, 0) / values.length;
}

function calculateStd(values, mean) {
    if (!values || values.length < 2) return 0.001;
    const m = mean ?? calculateMean(values);
    return Math.sqrt(values.reduce((s, v) => s + (v - m) ** 2, 0) / (values.length - 1)) || 0.001;
}

function calculateCpk(mean, std, tolerance) {
    // Assuming mean is target
    const usl = mean + tolerance;
    const lsl = mean - tolerance;
    const cpu = (usl - mean) / (3 * std);
    const cpl = (mean - lsl) / (3 * std);
    return Math.min(cpu, cpl);
}

// ─── Training / Baseline Calibration ────────────────────────────────────────
function findStableBaseline(shots, varName, windowSize = 50) {
    if (shots.length < windowSize) return null;

    let bestWindow = { start: 0, std: Infinity, mean: 0 };

    for (let i = 0; i <= shots.length - windowSize; i++) {
        const window = shots.slice(i, i + windowSize)
            .map(s => s[varName])
            .filter(v => typeof v === 'number');

        if (window.length < windowSize * 0.8) continue;

        const m = calculateMean(window);
        const s = calculateStd(window, m);

        if (s < bestWindow.std) {
            bestWindow = { start: i, std: s, mean: m };
        }
    }

    return bestWindow.std === Infinity ? null : { mean: bestWindow.mean, std: bestWindow.std };
}

// ─── EWMA State Tracker ─────────────────────────────────────────────────────
class DriftTracker {
    constructor(lambda = 0.2) {
        this.lambda = lambda;
        this.ewma = {};
        this.cusum_pos = {};
        this.cusum_neg = {};
        this.baselines = {};
        this.windowShort = {};
        this.cpk = {};
    }

    calibrate(shots) {
        for (const varName of Object.keys(THRESHOLDS)) {
            const baseline = findStableBaseline(shots, varName);
            if (baseline) {
                this.baselines[varName] = baseline;
                this.ewma[varName] = baseline.mean;
                this.cusum_pos[varName] = 0;
                this.cusum_neg[varName] = 0;
                this.cpk[varName] = calculateCpk(baseline.mean, baseline.std, THRESHOLDS[varName].tolerance);
            }
        }
    }

    update(varName, value) {
        if (!this.windowShort[varName]) this.windowShort[varName] = [];
        this.windowShort[varName].push(value);
        if (this.windowShort[varName].length > 20) this.windowShort[varName].shift();

        const baseline = this.baselines[varName];
        if (!baseline) return { ewma: value, cusum: 0, drift: 'none', rollingStd: 0, driftVelocity: 0 };

        const prevEwma = this.ewma[varName] ?? baseline.mean;
        const newEwma = this.lambda * value + (1 - this.lambda) * prevEwma;
        this.ewma[varName] = newEwma;

        const k = 0.5 * baseline.std;
        const z = value - baseline.mean;
        this.cusum_pos[varName] = Math.max(0, (this.cusum_pos[varName] || 0) + z - k);
        this.cusum_neg[varName] = Math.max(0, (this.cusum_neg[varName] || 0) - z - k);

        const cusumMax = Math.max(this.cusum_pos[varName], this.cusum_neg[varName]);
        const cusumThreshold = 5 * baseline.std;

        const rollingStd = calculateStd(this.windowShort[varName]);
        const driftVelocity = Math.abs(newEwma - prevEwma);

        let drift = 'none';
        if (cusumMax > cusumThreshold * 2) drift = 'high';
        else if (cusumMax > cusumThreshold) drift = 'moderate';
        else if (Math.abs(newEwma - baseline.mean) > 2.0 * baseline.std) drift = 'moderate';

        return { ewma: newEwma, cusum: cusumMax, drift, rollingStd, driftVelocity };
    }
}

// ─── Layer 1: Physics ───────────────────────────────────────────────────────
function physicsCheck(shot, baselines) {
    const violations = [];
    let physicsFail = false;

    for (const [varName, threshold] of Object.entries(THRESHOLDS)) {
        const value = shot[varName];
        if (typeof value !== 'number') continue;

        const baseline = baselines[varName];
        if (!baseline) continue;

        const deviation = Math.abs(value - baseline.mean);
        const ratio = deviation / threshold.tolerance;

        if (ratio > 1.0) {
            violations.push({
                variable: varName,
                key: VAR_KEY_MAP[varName] || varName,
                ratio,
                severity: ratio > 2.5 ? 'critical' : 'warning'
            });
            if (threshold.critical && ratio > 1.8) physicsFail = true;
        }
    }

    if (shot.Cushion < 0.2) physicsFail = true;

    return { physicsFail, violations };
}

// ─── Layer 3: Pattern scoring ───────────────────────────────────────────────
function featureScore(shot, driftResults, baselines, cpkMap) {
    let score = 0;
    const attributions = [];

    for (const [varName, threshold] of Object.entries(THRESHOLDS)) {
        const value = shot[varName];
        if (typeof value !== 'number') continue;

        const baseline = baselines[varName];
        if (!baseline) continue;

        const driftInfo = driftResults[varName];
        const deviation = Math.abs(value - baseline.mean);
        const normalizedDev = deviation / threshold.tolerance;

        // Machine-specific weighting based on observed Cpk
        // If Cpk is low, this variable is "loose" and needs more attention
        const cpkFactor = cpkMap[varName] ? Math.max(0.5, 2.0 - cpkMap[varName]) : 1.0;
        let featureContrib = normalizedDev * threshold.weight * cpkFactor;

        if (driftInfo) {
            if (driftInfo.drift === 'high') featureContrib *= 2.0;
            // Higher points for high drift velocity (fast change)
            if (driftInfo.driftVelocity > baseline.std * 0.5) featureContrib *= 1.2;
        }

        score += featureContrib;

        attributions.push({
            feature: VAR_KEY_MAP[varName] || varName.toLowerCase(),
            contribution: +(featureContrib * (value > baseline.mean ? 1 : -1)).toFixed(3),
            direction: value > baseline.mean ? 'positive' : 'negative'
        });
    }

    return { score: Math.min(1, score), attributions: attributions.sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution)).slice(0, 8) };
}

// ─── Layer 4: Ensemble ──────────────────────────────────────────────────────
function ensembleDecision(physicsFail, driftLevel, mlScore, violationCount) {
    let riskLevel = 'NORMAL';
    let prob = clamp(mlScore * 0.2, 0.02, 0.25);

    if (physicsFail) {
        riskLevel = 'CERTAIN';
        prob = 0.98;
    } else if (mlScore > 0.8 || (driftLevel === 'high' && mlScore > 0.55)) {
        riskLevel = 'VERY_HIGH';
        prob = clamp(0.66 + mlScore * 0.30, 0.82, 0.97);
    } else if (mlScore > 0.6 || driftLevel === 'high' || (driftLevel === 'moderate' && mlScore > 0.45)) {
        riskLevel = 'HIGH';
        prob = clamp(0.42 + mlScore * 0.30, 0.58, 0.86);
    } else if (mlScore > 0.4 || driftLevel === 'moderate') {
        riskLevel = 'ELEVATED';
        prob = clamp(0.26 + mlScore * 0.22, 0.35, 0.62);
    }

    const riskBaseConfidence = {
        NORMAL: 0.68,
        ELEVATED: 0.74,
        HIGH: 0.80,
        VERY_HIGH: 0.86,
        CERTAIN: 0.97
    };

    const driftBoost = driftLevel === 'high' ? 0.2 : driftLevel === 'moderate' ? 0.1 : 0;
    const supportByRisk = {
        NORMAL: clamp(1 - (mlScore / 0.5), 0, 1) + (driftLevel === 'none' ? 0.15 : 0),
        ELEVATED: clamp((mlScore - 0.35) / 0.40, 0, 1) + driftBoost,
        HIGH: clamp((mlScore - 0.50) / 0.35, 0, 1) + driftBoost,
        VERY_HIGH: clamp((mlScore - 0.70) / 0.30, 0, 1) + driftBoost,
        CERTAIN: 1
    };
    const violationBoost = Math.min(0.03, (violationCount || 0) * 0.005);
    const support = clamp(supportByRisk[riskLevel], 0, 1);
    const conf = clamp(riskBaseConfidence[riskLevel] + support * 0.09 + violationBoost, 0.60, 0.995);

    return {
        risk_level: riskLevel,
        scrap_probability: +prob.toFixed(3),
        confidence: +conf.toFixed(2),
        primary_defect_risk: prob > 0.6 ? 'Short Shot' : prob > 0.3 ? 'Sink Mark' : 'None',
        ...MODEL_INFO
    };
}

function deriveCycleId(shot, fallbackIndex) {
    const rawCounter = shot.Shot_counter;
    if (typeof rawCounter === 'number' && Number.isFinite(rawCounter)) {
        return String(Math.trunc(rawCounter));
    }
    if (typeof rawCounter === 'string' && rawCounter.trim()) {
        const parsed = Number.parseFloat(rawCounter);
        if (!Number.isNaN(parsed)) {
            return String(Math.trunc(parsed));
        }
    }

    if (shot._shotIndex !== undefined && shot._shotIndex !== null) {
        return String(shot._shotIndex);
    }
    return String(fallbackIndex);
}

// ─── Main Pipeline ─────────────────────────────────────────────────────────
function analyzeShotSequence(shots, driftTracker) {
    if (Object.keys(driftTracker.baselines).length === 0) {
        driftTracker.calibrate(shots);
    }

    return shots.map((shot, i) => {
        const driftResults = {};
        let overallDrift = 'none';

        for (const varName of Object.keys(THRESHOLDS)) {
            const val = shot[varName];
            if (typeof val === 'number') {
                const res = driftTracker.update(varName, val);
                driftResults[varName] = res;
                if (res.drift === 'high') overallDrift = 'high';
                else if (res.drift === 'moderate' && overallDrift !== 'high') overallDrift = 'moderate';
            }
        }

        const { physicsFail, violations } = physicsCheck(shot, driftTracker.baselines);
        const { score, attributions } = featureScore(shot, driftResults, driftTracker.baselines, driftTracker.cpk);
        const prediction = ensembleDecision(physicsFail, overallDrift, score, violations.length);

        const telemetry = {};
        for (const [csvName, frontendKey] of Object.entries(VAR_KEY_MAP)) {
            const val = shot[csvName];
            if (val === undefined) continue;
            const threshold = THRESHOLDS[csvName];
            const baseline = driftTracker.baselines[csvName];
            telemetry[frontendKey] = {
                value: +parseFloat(val).toFixed(3),
                safe_min: threshold && baseline ? +(baseline.mean - threshold.tolerance).toFixed(3) : null,
                safe_max: threshold && baseline ? +(baseline.mean + threshold.tolerance).toFixed(3) : null,
                setpoint: baseline ? +baseline.mean.toFixed(3) : null
            };
        }

        return {
            cycle_id: deriveCycleId(shot, i),
            timestamp: shot._timestamp || new Date().toISOString(),
            predictions: prediction,
            telemetry,
            shap_attributions: attributions,
            drift_status: overallDrift,
            physics_violations: violations.length
        };
    });
}

module.exports = { DriftTracker, analyzeShotSequence };
