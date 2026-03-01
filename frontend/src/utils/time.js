export function formatTelemetryTimestamp(timestamp) {
    if (!timestamp) return '—';
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return String(timestamp);

    return date.toLocaleString('en-IN', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
}

export function formatTelemetryTime(timestamp) {
    if (!timestamp) return '—';
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return String(timestamp);

    return date.toLocaleTimeString('en-IN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
}
