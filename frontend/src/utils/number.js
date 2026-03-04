export function toFiniteOrNull(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

export function toFixedSafe(value, digits = 2, fallback = 'N/A') {
  const num = toFiniteOrNull(value);
  return num === null ? fallback : num.toFixed(digits);
}

export function toNumberOr(value, fallback = 0) {
  const num = toFiniteOrNull(value);
  return num === null ? fallback : num;
}
