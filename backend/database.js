const sqlite3 = require('sqlite3');
const { open } = require('sqlite');
const path = require('path');

const DB_PATH = path.resolve(__dirname, 'factory_brain.db');
const DB_CACHE_SIZE = Number.parseInt(process.env.DB_CACHE_SIZE, 10) || -1000000;
const DB_SYNCHRONOUS = ['OFF', 'NORMAL', 'FULL', 'EXTRA'].includes((process.env.DB_SYNCHRONOUS || '').toUpperCase())
    ? process.env.DB_SYNCHRONOUS.toUpperCase()
    : 'NORMAL';
const DB_TEMP_STORE = ['DEFAULT', 'FILE', 'MEMORY'].includes((process.env.DB_TEMP_STORE || '').toUpperCase())
    ? process.env.DB_TEMP_STORE.toUpperCase()
    : 'MEMORY';
const DB_JOURNAL_MODE = ['DELETE', 'TRUNCATE', 'PERSIST', 'MEMORY', 'WAL', 'OFF'].includes((process.env.DB_JOURNAL_MODE || '').toUpperCase())
    ? process.env.DB_JOURNAL_MODE.toUpperCase()
    : 'WAL';

let db;

async function initDB() {
    db = await open({
        filename: DB_PATH,
        driver: sqlite3.Database
    });

    // Optimize for performance
    await db.exec(`PRAGMA journal_mode = ${DB_JOURNAL_MODE}`);
    await db.exec(`PRAGMA synchronous = ${DB_SYNCHRONOUS}`);
    await db.exec(`PRAGMA cache_size = ${DB_CACHE_SIZE}`);
    await db.exec(`PRAGMA temp_store = ${DB_TEMP_STORE}`);

    await db.exec(`
        CREATE TABLE IF NOT EXISTS cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT,
            cycle_id TEXT,
            timestamp TEXT,
            data JSON,
            UNIQUE(machine_id, timestamp)
        );

        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id INTEGER,
            scrap_probability REAL,
            confidence REAL,
            risk_level TEXT,
            primary_defect_risk TEXT,
            attributions JSON,
            FOREIGN KEY(cycle_id) REFERENCES cycles(id)
        );

        CREATE TABLE IF NOT EXISTS machine_stats (
            machine_id TEXT PRIMARY KEY,
            baselines JSON,
            last_loaded_timestamp TEXT
        );
    `);

    console.log('✅ SQLite database initialized and optimized.');
    return db;
}

async function saveCyclesBulk(machineId, cycles) {
    if (!cycles || cycles.length === 0) return;

    try {
        await db.run('BEGIN TRANSACTION');

        const stmtCycle = await db.prepare('INSERT OR IGNORE INTO cycles (machine_id, cycle_id, timestamp, data) VALUES (?, ?, ?, ?)');
        const stmtPred = await db.prepare('INSERT INTO predictions (cycle_id, scrap_probability, confidence, risk_level, primary_defect_risk, attributions) VALUES (?, ?, ?, ?, ?, ?)');

        for (const cycle of cycles) {
            const { cycle_id, timestamp, telemetry, predictions, shap_attributions } = cycle;
            const result = await stmtCycle.run([machineId, cycle_id, timestamp, JSON.stringify(telemetry)]);

            if (result.lastID) {
                await stmtPred.run([
                    result.lastID,
                    predictions.scrap_probability,
                    predictions.confidence,
                    predictions.risk_level,
                    predictions.primary_defect_risk,
                    JSON.stringify(shap_attributions)
                ]);
            }
        }

        await stmtCycle.finalize();
        await stmtPred.finalize();
        await db.run('COMMIT');
        console.log(`  ✅ ${machineId}: Bulk saved ${cycles.length} cycles to SQLite.`);
    } catch (err) {
        await db.run('ROLLBACK');
        console.error(`  ❌ Error in bulk save for ${machineId}:`, err);
    }
}

async function saveCycle(machineId, cycle) {
    const { cycle_id, timestamp, telemetry, predictions, shap_attributions } = cycle;
    try {
        const result = await db.run(
            'INSERT OR IGNORE INTO cycles (machine_id, cycle_id, timestamp, data) VALUES (?, ?, ?, ?)',
            [machineId, cycle_id, timestamp, JSON.stringify(telemetry)]
        );

        if (result.lastID) {
            await db.run(
                'INSERT INTO predictions (cycle_id, scrap_probability, confidence, risk_level, primary_defect_risk, attributions) VALUES (?, ?, ?, ?, ?, ?)',
                [
                    result.lastID,
                    predictions.scrap_probability,
                    predictions.confidence,
                    predictions.risk_level,
                    predictions.primary_defect_risk,
                    JSON.stringify(shap_attributions)
                ]
            );
        }
    } catch (err) {
        console.error(`Error saving cycle for ${machineId}:`, err);
    }
}

async function getMachineHistory(machineId, limit = 500) {
    const rows = await db.all(`
        SELECT c.*, p.scrap_probability, p.confidence, p.risk_level, p.primary_defect_risk, p.attributions 
        FROM cycles c
        LEFT JOIN predictions p ON c.id = p.cycle_id
        WHERE c.machine_id = ?
        ORDER BY c.timestamp DESC
        LIMIT ?
    `, [machineId, limit]);

    return rows.reverse().map(row => ({
        cycle_id: row.cycle_id,
        timestamp: row.timestamp,
        telemetry: JSON.parse(row.data),
        predictions: {
            scrap_probability: row.scrap_probability,
            confidence: row.confidence,
            risk_level: row.risk_level,
            primary_defect_risk: row.primary_defect_risk
        },
        shap_attributions: JSON.parse(row.attributions || '[]')
    }));
}

async function updateMachineStats(machineId, baselines, lastTimestamp) {
    await db.run(
        'INSERT OR REPLACE INTO machine_stats (machine_id, baselines, last_loaded_timestamp) VALUES (?, ?, ?)',
        [machineId, JSON.stringify(baselines), lastTimestamp]
    );
}

async function getMachineStats(machineId) {
    return await db.get('SELECT * FROM machine_stats WHERE machine_id = ?', [machineId]);
}

module.exports = {
    initDB,
    saveCycle,
    saveCyclesBulk,
    getMachineHistory,
    updateMachineStats,
    getMachineStats
};
