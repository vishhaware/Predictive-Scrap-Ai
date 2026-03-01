const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { createMachineIdValidator, listMachineIdsFromDataDir, resolveMachineId, parseLimit } = require('../apiValidation');

test('createMachineIdValidator validates known ids', () => {
    const isValidMachineId = createMachineIdValidator(['M1', 'M2']);
    assert.equal(isValidMachineId('M1'), true);
    assert.equal(isValidMachineId('M3'), false);
});

test('parseLimit clamps and defaults safely', () => {
    assert.equal(parseLimit(undefined, 1000, 500), 500);
    assert.equal(parseLimit('abc', 1000, 500), 500);
    assert.equal(parseLimit('-1', 1000, 500), 500);
    assert.equal(parseLimit('2000', 1000, 500), 1000);
    assert.equal(parseLimit('250', 1000, 500), 250);
});

test('listMachineIdsFromDataDir loads csv-based machine ids', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'factory-machine-ids-'));
    fs.writeFileSync(path.join(tmpDir, 'M612-33.csv'), 'timestamp,variable_name,value\n');
    fs.writeFileSync(path.join(tmpDir, 'M231-11.csv'), 'timestamp,variable_name,value\n');
    fs.writeFileSync(path.join(tmpDir, 'notes.txt'), 'ignore me\n');

    const ids = listMachineIdsFromDataDir(tmpDir, ['X1']);

    assert.deepEqual(ids, ['M231-11', 'M612-33']);
    fs.rmSync(tmpDir, { recursive: true, force: true });
});

test('resolveMachineId returns a detailed message for ambiguous ids', () => {
    const result = resolveMachineId('m', ['M231-11', 'M356-57', 'M471-23']);

    assert.equal(result.ok, false);
    assert.match(result.error, /Ambiguous machine id "m"\./);
    assert.match(result.error, /Did you mean: M231-11, M356-57, M471-23\?/);
    assert.match(result.error, /Valid IDs: M231-11, M356-57, M471-23/);
});

test('resolveMachineId accepts exact and unique prefix ids', () => {
    const exact = resolveMachineId('M356-57', ['M231-11', 'M356-57', 'M471-23']);
    const prefix = resolveMachineId('M356', ['M231-11', 'M356-57', 'M471-23']);

    assert.deepEqual(exact, { ok: true, machineId: 'M356-57' });
    assert.deepEqual(prefix, { ok: true, machineId: 'M356-57' });
});
