import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '../test/render'
import { AppLayout } from './AppLayout'

describe('AppLayout', () => {
  it('links to the queue, all quotes and the dashboard and renders the routed page', () => {
    renderWithProviders(
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<p>page body</p>} />
        </Route>
      </Routes>,
    )

    expect(screen.getByRole('link', { name: 'Review queue' })).toHaveAttribute('href', '/')
    expect(screen.getByRole('link', { name: 'All quotes' })).toHaveAttribute('href', '/quotes')
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('href', '/dashboard')
    expect(screen.getByText('page body')).toBeInTheDocument()
  })
})
