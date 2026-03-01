const fs = require('fs');
const path = require('path');

const DEFAULT_MACHINE_IDS = ['M231-11', 'M356-57', 'M471-23', 'M607-30', 'M612-33'];

function listMachineIdsFromDataDir(dataDir, fallbackMachineIds = DEFAULT_MACHINE_IDS) {
    try {
        if (!fs.existsSync(dataDir)) return [...fallbackMachineIds];
        const ids = fs.readdirSync(dataDir)
            .filter((name) => name.toLowerCase().endsWith('.csv'))
            .map((name) => path.basename(name, '.csv'))
            .sort();
        return ids.length > 0 ? ids : [...fallbackMachineIds];
    } catch (error) {
        return [...fallbackMachineIds];
    }
}

function createMachineIdValidator(machineIds = DEFAULT_MACHINE_IDS) {
    const machineIdSet = new Set(machineIds);
    return function isValidMachineId(machineId) {
        return machineIdSet.has(machineId);
    };
}

function resolveMachineId(rawMachineId, machineIds = DEFAULT_MACHINE_IDS) {
    const input = String(rawMachineId || '').trim();
    const validList = [...machineIds].sort();

    if (!input) {
        return {
            ok: false,
            error: `Missing machine id. Valid IDs: ${validList.join(', ')}`
        };
    }

    if (validList.includes(input)) {
        return { ok: true, machineId: input };
    }

    const normalized = input.toLowerCase();
    const startsWithMatches = validList.filter((id) => id.toLowerCase().startsWith(normalized));

    if (startsWithMatches.length === 1) {
        return { ok: true, machineId: startsWithMatches[0] };
    }

    if (startsWithMatches.length > 1) {
        return {
            ok: false,
            error: `Ambiguous machine id "${input}". Did you mean: ${startsWithMatches.join(', ')}? Valid IDs: ${validList.join(', ')}`
        };
    }

    return {
        ok: false,
        error: `Unknown machine id "${input}". Valid IDs: ${validList.join(', ')}`
    };
}

function parseLimit(rawLimit, maxLimit = 1000, defaultLimit = 500) {
    const parsed = Number.parseInt(rawLimit, 10);
    if (Number.isNaN(parsed) || parsed <= 0) return defaultLimit;
    return Math.min(parsed, maxLimit);
}

module.exports = {
    DEFAULT_MACHINE_IDS,
    listMachineIdsFromDataDir,
    createMachineIdValidator,
    resolveMachineId,
    parseLimit
};
