import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { estimate } from '../test/fixtures'
import { JudgePanel } from './JudgePanel'

describe('JudgePanel', () => {
  it('says so when the estimate was never judged', () => {
    render(<JudgePanel verdict={null} />)

    expect(screen.getByText('Not judged yet.')).toBeInTheDocument()
  })

  it('explains the guardrail fast path, where no model ran', () => {
    const verdict = { ...estimate().judge_verdict!, dimensions: [], model: 'none (guardrail fast path)' }

    render(<JudgePanel verdict={verdict} />)

    expect(screen.getByText('The guardrails blocked this draft before the judge ran.')).toBeInTheDocument()
  })

  it('shows each dimension score with its rationale', () => {
    render(<JudgePanel verdict={estimate().judge_verdict} />)

    expect(screen.getByText('price is a prediction')).toBeInTheDocument()
    expect(screen.getByText('Needs review')).toBeInTheDocument()
    expect(screen.getByText('Price source')).toBeInTheDocument()
  })
})
