import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RichText } from './RichText'

describe('RichText', () => {
  it('renders inline markdown instead of showing raw asterisks and backticks', () => {
    const { container } = render(<RichText>{'price is **not** a list price for `SKU-1`'}</RichText>)

    expect(container.textContent).toBe('price is not a list price for SKU-1')
    expect(container.querySelector('strong')?.textContent).toBe('not')
    expect(container.querySelector('code')?.textContent).toBe('SKU-1')
  })

  it('keeps block markdown and raw HTML from the model out of the page', () => {
    const { container } = render(<RichText>{'# Heading\n\n<script>alert(1)</script> [link](http://x.test)'}</RichText>)

    expect(container.querySelector('h1, script, a')).toBeNull()
    expect(container.textContent).toContain('Heading')
    expect(container.textContent).toContain('link')
  })
})
