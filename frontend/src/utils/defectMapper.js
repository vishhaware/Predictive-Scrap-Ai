// Maps dominant SHAP features + physics signals → defect + corrective actions
export const DEFECT_MAP = {
    cushion: {
        defect: 'Short Shot / Non-fill',
        mechanism: 'Cushion collapsing to 0 mm indicates material starvation at pack stage.',
        actions: [
            'Increase injection pressure and speed',
            'Check for blocked gate or runner',
            'Ensure sufficient material feed in hopper',
            'Verify decompression settings are not excessive',
        ],
        bucket: 'A',
    },
    injection_pressure: {
        defect: 'Flash / Parting Line Overflow',
        mechanism: 'Excessive peak injection pressure forces material past mold parting surfaces.',
        actions: [
            'Reduce injection speed in initial fill stage',
            'Check clamp tonnage — may be insufficient',
            'Lower melt temperature to increase viscosity',
            'Inspect mold parting surfaces for wear',
        ],
        bucket: 'B',
    },
    switch_pressure: {
        defect: 'Short Shot or Parting Line Flash',
        mechanism: 'Switch-over pressure too high or too low causes fill/pack imbalance.',
        actions: [
            'Adjust V/P transfer position — currently at wrong stroke',
            'Verify pressure transducer calibration',
            'Reduce screw decompression before refill',
        ],
        bucket: 'B',
    },
    holding_pressure: {
        defect: 'Sink Marks / Internal Voids',
        mechanism: 'Insufficient holding pressure prevents adequate packing of thick wall sections.',
        actions: [
            'Increase packing time and holding pressure',
            'Extend cooling phase before ejection',
            'Improve mold cooling efficiency (water temperature)',
        ],
        bucket: 'B',
    },
    temp_z2: {
        defect: 'Burn Marks / Degraded Melt',
        mechanism: 'Excessive barrel temperature causes polymer degradation and trapped gas.',
        actions: [
            'Reduce melt temperature in Zone 2',
            'Slow injection speed to allow gas to escape',
            'Enlarge or clean gas vents in mold',
            'Check for hot-spot in barrel via thermal imaging',
        ],
        bucket: 'A',
    },
    temp_z1: {
        defect: 'Incomplete Melting / Material Streaks',
        mechanism: 'Feed zone temperature anomaly causes inconsistent plastication.',
        actions: [
            'Normalize Zone 1 temperature per material datasheet',
            'Tune screw RPM to improve melt homogeneity',
            'Check screw for wear or bridging in feed zone',
        ],
        bucket: 'A',
    },
    dosage_time: {
        defect: 'Cushion Instability / Part Starvation',
        mechanism: 'Dosage time variation influences part filling and cushion level. High deviation indicates inconsistent plastication.',
        actions: [
            'Adjust dosing speed (RPM) to normalize dosage time',
            'Check for blocked gates or venting issues',
            'Ensure consistent hopper feed rate',
            'Inspect screw flights for material build-up',
        ],
        bucket: 'A',
    },
};

export function getTopDefect(shapAttributions) {
    if (!shapAttributions?.length) return null;
    const sorted = [...shapAttributions].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
    const top = sorted[0];
    return DEFECT_MAP[top.feature] ?? null;
}

export function buildNarrativeSummary(shapAttributions, telemetry) {
    if (!shapAttributions?.length) return '';
    const sorted = [...shapAttributions].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
    const top1 = sorted[0];
    const top2 = sorted[1];

    const tele1 = telemetry?.[top1.feature];
    const tele2 = telemetry?.[top2?.feature];

    const dirLabel1 = top1.direction === 'positive' ? 'elevated' : 'suppressed';
    const val1 = tele1 ? ` (${tele1.value}${tele1.setpoint ? ` vs setpoint ${tele1.setpoint}` : ''})` : '';
    const val2 = tele2 ? ` (${tele2.value})` : '';

    const featureLabel = f => f.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

    return `${featureLabel(top1.feature)}${val1} is ${dirLabel1} — primary scrap driver (SHAP: +${top1.contribution.toFixed(2)}). ` +
        `${top2 ? `${featureLabel(top2.feature)}${val2} is secondary contributor.` : ''}`;
}
