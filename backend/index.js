/**
 * index.js — Smart Factory Brain Backend (Optimized with SQLite)
 */

const express = require('express');
const http = require('http');
const WebSocket = require('ws');
const cors = require('cors');
const fs = require('fs');
const path = require('path');
const { parse } = require('csv-parse');
const { analyzeShotSequence, DriftTracker } = require('./engine');
const { listMachineIdsFromDataDir, resolveMachineId, parseLimit } = require('./apiValidation');
const db = require('./database');

const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

// ─── Configuration ───────────────────────────────────────────────────────────
const DEFAULT_MACHINE_NAMES = {
    'M231-11': 'Engel ES-200',
    'M356-57': 'Arburg 370S',
    'M471-23': 'Haitian J300',
    'M607-30': 'JSW J85E-II',
    'M612-33': 'Fanuc S-2000i',
};
const DATA_DIR = process.env.DATA_DIR
    ? path.resolve(process.env.DATA_DIR)
    : path.resolve(__dirname, '..', 'frontend', 'Data');
const MACHINE_IDS = listMachineIdsFromDataDir(DATA_DIR);
const MACHINE_NAMES = Object.fromEntries(
    MACHINE_IDS.map((id) => [id, DEFAULT_MACHINE_NAMES[id] || id])
);
const PORT = Number.parseInt(process.env.PORT, 10) || 3001;
const MAX_CYCLES_LIMIT = Number.parseInt(process.env.MAX_CYCLES_LIMIT, 10) || 1000;
const ALLOWED_ORIGINS = (process.env.CORS_ORIGINS || '')
    .split(',')
    .map(origin => origin.trim())
    .filter(Boolean);

app.use(cors({
    origin: ALLOWED_ORIGINS.length > 0 ? ALLOWED_ORIGINS : true
}));
app.use(express.json({ limit: '1mb' }));

const machineContext = {}; // machineId -> { driftTracker }
const serviceState = {
    backend: 'node',
    startup: 'starting',
    startupError: null,
    startupCompletedAt: null
};

function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
}

function toFiniteNumber(value) {
    const num = Number(value);
    return Number.isFinite(num) ? num : null;
}

function calibrateConfidenceFromHistory(history) {
    if (!Array.isArray(history) || history.length === 0) return [];

    let prevScrapCounter = null;
    let brierEwma = 0.18; // ~82% prior reliability

    return history.map((cycle) => {
        const predictions = cycle?.predictions || {};
        const prob = clamp(toFiniteNumber(predictions.scrap_probability) ?? 0, 0, 1);
        const rawConfidence = clamp(toFiniteNumber(predictions.confidence) ?? 0.8, 0, 1);

        const scrapCounter = toFiniteNumber(cycle?.telemetry?.scrap_counter?.value);
        let actualScrap = null;
        if (scrapCounter !== null && prevScrapCounter !== null) {
            actualScrap = scrapCounter > prevScrapCounter ? 1 : 0;
        }
        if (scrapCounter !== null) {
            prevScrapCounter = scrapCounter;
        }

        if (actualScrap !== null) {
            const brier = (prob - actualScrap) ** 2;
            brierEwma = (0.9 * brierEwma) + (0.1 * brier);
        }

        const empiricalConfidence = clamp(1 - brierEwma, 0, 1);
        const blendedConfidence = clamp((rawConfidence * 0.35) + (empiricalConfidence * 0.65), 0.55, 0.97);

        return {
            ...cycle,
            predictions: {
                ...predictions,
                confidence: +blendedConfidence.toFixed(3),
                confidence_raw: +rawConfidence.toFixed(3),
                confidence_empirical: +empiricalConfidence.toFixed(3),
                confidence_method: 'calibrated_brier_ewma'
            }
        };
    });
}

// ─── CSV Parser Helper ──────────────────────────────────────────────────────
function parseCSV(filePath, lastTimestamp) {
    return new Promise((resolve, reject) => {
        const shotMap = new Map();
        let lastSeenTs = lastTimestamp;

        const parser = fs.createReadStream(filePath)
            .pipe(parse({ columns: true, skip_empty_lines: true, trim: true }));

        parser.on('data', (row) => {
            const ts = row.timestamp;
            if (lastTimestamp && ts <= lastTimestamp) return;

            if (!shotMap.has(ts)) {
                shotMap.set(ts, { _timestamp: ts });
            }
            const shot = shotMap.get(ts);
            const num = parseFloat(row.value);
            shot[row.variable_name] = isNaN(num) ? row.value : num;
            if (!lastSeenTs || ts > lastSeenTs) lastSeenTs = ts;
        });

        parser.on('end', () => {
            const shots = Array.from(shotMap.values()).sort((a, b) => a._timestamp.localeCompare(b._timestamp));
            resolve({ shots, lastTimestamp: lastSeenTs });
        });

        parser.on('error', reject);
    });
}

// ─── Startup Logic ───────────────────────────────────────────────────────────
async function startup() {
    await db.initDB();
    serviceState.startup = 'loading';
    serviceState.startupError = null;
    console.log('\n🏭 Smart Factory Brain — Optimizing data layers...\n');
    console.log(`  📦 Loaded machine catalog from ${DATA_DIR}: ${MACHINE_IDS.join(', ')}`);

    for (const machineId of MACHINE_IDS) {
        machineContext[machineId] = { driftTracker: new DriftTracker() };

        const stats = await db.getMachineStats(machineId);
        const filePath = path.join(DATA_DIR, `${machineId}.csv`);

        if (!fs.existsSync(filePath)) {
            console.warn(`  ⚠ Machine ${machineId}: CSV not found.`);
            continue;
        }

        let newShots = [];
        let currentBaselines = stats ? JSON.parse(stats.baselines) : {};
        let lastTs = stats ? stats.last_loaded_timestamp : null;

        if (!lastTs) {
            console.log(`  📂 ${machineId}: First-time ingestion (parsing CSV)...`);
        } else {
            console.log(`  💾 ${machineId}: Found cached data in SQLite. Checking for updates...`);
        }

        const result = await parseCSV(filePath, lastTs);
        newShots = result.shots;

        if (newShots.length > 0) {
            console.log(`  ⚙️ ${machineId}: Processing ${newShots.length} new shots...`);
            const analyzed = analyzeShotSequence(newShots, machineContext[machineId].driftTracker);

            // Save to DB in bulk
            await db.saveCyclesBulk(machineId, analyzed);

            await db.updateMachineStats(
                machineId,
                machineContext[machineId].driftTracker.baselines,
                result.lastTimestamp
            );
        } else {
            // If no new shots, restore drift tracker state from stats
            if (stats) {
                machineContext[machineId].driftTracker.baselines = currentBaselines;
            }
            console.log(`  ✅ ${machineId}: Up to date.`);
        }
    }

    console.log('\n🚀 Backend optimized and ready.\n');
    serviceState.startup = 'ready';
    serviceState.startupCompletedAt = new Date().toISOString();
}

// ─── REST API ────────────────────────────────────────────────────────────────
app.get('/', (req, res) => {
    res.json({
        ok: true,
        backend: 'node',
        message: 'Smart Factory Brain backend is running.',
        endpoints: ['/api/health', '/api/machines', '/api/machines/:id/cycles', '/ws']
    });
});

app.get('/api/health', async (req, res) => {
    res.json({
        ok: true,
        ...serviceState,
        uptimeSec: Math.round(process.uptime())
    });
});

app.get('/api/machines', async (req, res) => {
    try {
        const list = await Promise.all(MACHINE_IDS.map(async id => {
            const history = calibrateConfidenceFromHistory(await db.getMachineHistory(id, 50));
            const last = history[history.length - 1];
            return {
                id,
                name: MACHINE_NAMES[id],
                status: last?.predictions.risk_level === 'CERTAIN' || last?.predictions.risk_level === 'VERY_HIGH' ? 'crit' :
                    last?.predictions.risk_level === 'HIGH' ? 'warn' : 'ok',
                oee: last ? Math.round(100 * (1 - last.predictions.scrap_probability)) : 0,
                scraps: 0, // Simplified for now
                temp: last?.telemetry.temp_z1?.value || 230,
                cycles: last ? parseInt(last.cycle_id, 10) : 0
            };
        }));
        res.json(list);
    } catch (error) {
        console.error('Failed to fetch machine summaries:', error);
        res.status(500).json({ error: 'Failed to fetch machine summaries' });
    }
});

app.get('/api/machines/:id/cycles', async (req, res) => {
    const machineMatch = resolveMachineId(req.params.id, MACHINE_IDS);
    if (!machineMatch.ok) {
        return res.status(400).json({ error: machineMatch.error });
    }
    const machineId = machineMatch.machineId;

    const limit = parseLimit(req.query.limit, MAX_CYCLES_LIMIT, 500);

    try {
        const history = calibrateConfidenceFromHistory(await db.getMachineHistory(machineId, limit));
        return res.json(history);
    } catch (error) {
        console.error(`Failed to fetch history for ${machineId}:`, error);
        return res.status(500).json({ error: 'Failed to fetch machine history' });
    }
});

// ─── WebSocket ───────────────────────────────────────────────────────────────
wss.on('connection', (ws) => {
    let machineId = MACHINE_IDS[0] || 'M231-11';
    let ticker;

    ws.on('message', (msg) => {
        let data;
        try {
            data = JSON.parse(msg.toString());
        } catch (error) {
            ws.send(JSON.stringify({ type: 'error', message: 'Invalid JSON message' }));
            return;
        }

        if (data.type === 'switch_machine') {
            const machineMatch = resolveMachineId(data.machine_id, MACHINE_IDS);
            if (!machineMatch.ok) {
                ws.send(JSON.stringify({ type: 'error', message: machineMatch.error }));
                return;
            }

            machineId = machineMatch.machineId;
            void startStreaming();
            return;
        }

        if (data.type === 'ping') {
            ws.send(JSON.stringify({ type: 'pong' }));
            return;
        }

        ws.send(JSON.stringify({ type: 'error', message: 'Unsupported message type' }));
    });

    async function startStreaming() {
        if (ticker) clearInterval(ticker);

        try {
            const history = calibrateConfidenceFromHistory(await db.getMachineHistory(machineId, 20));
            let idx = 0;

            ticker = setInterval(() => {
                if (history.length === 0 || ws.readyState !== WebSocket.OPEN) return;
                const cycle = history[idx % history.length];
                ws.send(JSON.stringify({ type: 'cycle_update', machine_id: machineId, cycle }));
                idx++;
            }, 3000);
        } catch (error) {
            console.error(`Failed streaming setup for ${machineId}:`, error);
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'error', message: 'Failed to load machine stream' }));
            }
        }
    }

    ws.on('close', () => clearInterval(ticker));

    // Stream immediately for clients that do not explicitly send switch_machine.
    void startStreaming();
});

wss.on('error', (error) => {
    console.error('WebSocket server error:', error);
});

server.on('error', (error) => {
    if (error.code === 'EADDRINUSE') {
        console.error(`Port ${PORT} is already in use. Stop the running process or set a different PORT.`);
    } else {
        console.error('HTTP server error:', error);
    }
    process.exit(1);
});

startup()
    .then(() => {
        server.listen(PORT, () => console.log(`🚀 Live on http://localhost:${PORT}`));
    })
    .catch((error) => {
        serviceState.startup = 'failed';
        serviceState.startupError = String(error?.message || error);
        console.error('Backend startup failed:', error);
        process.exit(1);
    });
