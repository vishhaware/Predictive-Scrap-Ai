// i18n utility — English only
const translations = {
    en: {
        operatorView: 'Operator Dashboard',
        engineerView: 'Process Engineer',
        managerView: 'Plant Manager',
        scrapProbability: 'Scrap Probability',
        cycleId: 'Cycle ID',
        defectRisk: 'Defect Risk',
        cushion: 'Cushion',
        injectionPressure: 'Injection Pressure',
        holdingPressure: 'Holding Pressure',
        switchPressure: 'Switch Pressure',
        rootCause: 'Root Cause Analysis',
        corrective: 'Corrective Actions',
        acknowledge: 'Acknowledge',
        viewDiagnostics: 'View Diagnostics',
        eStop: 'E-Stop',
        nominalBand: 'Nominal Band',
        measured: 'Measured',
        setpoint: 'Setpoint',
        alertCenter: 'Alert Center',
        auditLog: 'Audit Log',
        fleetOverview: 'Fleet Overview',
        oee: 'OEE',
        scrapsThisShift: 'Scraps This Shift',
        machineStatus: 'Machine Status',
        normalOp: 'Normal Operation',
        criticalAlert: 'Critical Alert',
        driftWarning: 'Drift Warning',
        shortShot: 'Short Shot',
        sinkMark: 'Sink Mark',
        flash: 'Flash',
        burnMark: 'Burn Mark',
        warping: 'Warping',
        increaseInjP: 'Increase injection pressure and speed',
        checkGate: 'Check for blocked gate or runner',
        ensureMaterial: 'Ensure sufficient material feed',
        increaseHoldP: 'Increase packing time and holding pressure',
        extendCooling: 'Extend cooling phase',
        reduceMeltTemp: 'Reduce melt temperature',
        reduceInjSpeed: 'Reduce injection speed',
        checkClamp: 'Check clamp tonnage for inadequacy',
    }
};

export function t(key) {
    // Always fallback to 'en' as we are removing other languages
    return translations.en[key] ?? key;
}
