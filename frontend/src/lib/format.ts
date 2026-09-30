const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

export function money(value: number | null | undefined): string {
  return value === null || value === undefined ? 'Not recorded' : currency.format(value)
}

export function percent(value: number | null): string {
  return value === null ? 'no data yet' : `${(value * 100).toFixed(1)}%`
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })
}

/** The backend's `detail` string is the message a reviewer needs (already resolved, bad correction), so it is
 * shown as written. */
export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'object' && error !== null && 'detail' in error) {
    const { detail } = error as { detail: unknown }
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail.map((entry) => (typeof entry?.msg === 'string' ? entry.msg : JSON.stringify(entry))).join('; ')
    }
  }
  return 'The request failed.'
}
