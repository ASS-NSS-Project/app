/**
 * utils/time.ts — Date/time formatting helpers
 *
 * All timestamps from the API are stored as UTC ISO-8601 strings without a
 * timezone suffix (e.g. "2024-06-01T12:00:00"). The JavaScript Date constructor
 * treats those as *local* time unless we append "Z". The helpers here normalise
 * that before formatting so timestamps always display correctly regardless of the
 * server's timezone configuration.
 */

/**
 * Parse an ISO-8601 string as UTC regardless of whether it has a "Z" suffix.
 * PostgreSQL timestamps stored without timezone lack the "Z", so we add it if
 * neither "Z" nor an offset ("+") is already present.
 */
function utcDate(iso: string): Date {
  return new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
}

/**
 * Return a short human-readable "time ago" string from an ISO-8601 timestamp.
 * Examples: "42s ago", "5m ago", "3h ago", "2d ago".
 * Used in table rows and incident cards to keep the UI compact.
 */
export function relTime(iso: string): string {
  const diff = Date.now() - utcDate(iso).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

/**
 * Format an ISO-8601 timestamp as a short locale-aware date+time string.
 * Returns something like "06/01/2024 14:30" in 24-hour format.
 * Used in the audit log table and the API token expiry display.
 */
export function fmtDatetime(iso: string): string {
  return utcDate(iso).toLocaleString([], {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
    hour12: false,
  }).replace(',', '')  // some locales insert a comma between date and time
}
