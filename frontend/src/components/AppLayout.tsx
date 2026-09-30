import { Layout, Menu } from 'antd'
import { Link, Outlet, useLocation } from 'react-router'

const { Header, Content } = Layout

function selectedKey(pathname: string): string {
  if (pathname.startsWith('/dashboard')) return 'dashboard'
  if (pathname.startsWith('/graph')) return 'graph'
  if (pathname.startsWith('/quotes')) return 'quotes'
  return 'queue'
}

export function AppLayout() {
  const { pathname } = useLocation()
  return (
    <Layout className="min-h-screen">
      <Header className="flex items-center gap-8">
        <span className="text-lg font-semibold text-white">Estimate Review</span>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[selectedKey(pathname)]}
          className="flex-1"
          items={[
            { key: 'queue', label: <Link to="/">Review queue</Link> },
            { key: 'quotes', label: <Link to="/quotes">All quotes</Link> },
            { key: 'graph', label: <Link to="/graph">Graph</Link> },
            { key: 'dashboard', label: <Link to="/dashboard">Dashboard</Link> },
          ]}
        />
      </Header>
      <Content className="mx-auto w-full max-w-6xl p-6">
        <Outlet />
      </Content>
    </Layout>
  )
}
