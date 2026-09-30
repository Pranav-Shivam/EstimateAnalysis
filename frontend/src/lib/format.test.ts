import { describe, expect, it } from 'vitest'
import { dateTime, errorMessage, money, percent } from './format'

describe('money', () => {
  it('formats dollars and marks a missing amount', () => {
    expect(money(1234.5)).toBe('$1,234.50')
    expect(money(null)).toBe('n/a')
    expect(money(undefined)).toBe('n/a')
  })
})

describe('percent', () => {
  it('formats a rate to one decimal and says "no data yet" for a null rate', () => {
    expect(percent(0.7)).toBe('70.0%')
    expect(percent(0)).toBe('0.0%')
    expect(percent(null)).toBe('no data yet')
  })
})

describe('dateTime', () => {
  it('renders a timestamp in a short readable form', () => {
    expect(dateTime('2030-01-01T12:05:00')).toMatch(/Jan 1, 2030/)
  })
})

describe('errorMessage', () => {
  it('returns the backend detail string verbatim', () => {
    expect(errorMessage({ detail: 'review item abc is already corrected' })).toBe(
      'review item abc is already corrected',
    )
  })

  it('joins request validation errors', () => {
    expect(errorMessage({ detail: [{ msg: 'field required' }, { msg: 'bad value' }] })).toBe(
      'field required; bad value',
    )
  })

  it('falls back to an Error message, then to a generic sentence', () => {
    expect(errorMessage(new Error('network down'))).toBe('network down')
    expect(errorMessage(undefined)).toBe('The request failed.')
  })
})
