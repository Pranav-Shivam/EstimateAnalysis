import { Route, Routes } from 'react-router'
import { AppLayout } from './components/AppLayout'
import { DashboardPage } from './pages/DashboardPage'
import { GraphPage } from './pages/GraphPage'
import { QueuePage } from './pages/QueuePage'
import { QuoteDetailPage } from './pages/QuoteDetailPage'
import { QuotesPage } from './pages/QuotesPage'

export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<QueuePage />} />
        <Route path="quotes" element={<QuotesPage />} />
        <Route path="quotes/:id" element={<QuoteDetailPage />} />
        <Route path="graph" element={<GraphPage />} />
        <Route path="dashboard" element={<DashboardPage />} />
      </Route>
    </Routes>
  )
}
