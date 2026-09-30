import { ApartmentOutlined, AuditOutlined, BarChartOutlined, FileTextOutlined } from '@ant-design/icons'
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
      <Header className="sticky top-0 z-10 flex items-center gap-4 border-b sm:gap-8 border-slate-200">
        <Link to="/" className="flex shrink-0 items-center gap-2 text-slate-900">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">
            ER
          </span>
          <span className="hidden text-base font-semibold tracking-tight sm:inline">Estimate Review</span>
        </Link>
        <Menu
          mode="horizontal"
          selectedKeys={[selectedKey(pathname)]}
          className="min-w-0 flex-1 border-none"
          items={[
            { key: 'queue', icon: <AuditOutlined />, label: <Link to="/">Review queue</Link> },
            { key: 'quotes', icon: <FileTextOutlined />, label: <Link to="/quotes">All quotes</Link> },
            { key: 'graph', icon: <ApartmentOutlined />, label: <Link to="/graph">Graph</Link> },
            { key: 'dashboard', icon: <BarChartOutlined />, label: <Link to="/dashboard">Dashboard</Link> },
          ]}
        />
      </Header>
      <Content className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6">
        <Outlet />
      </Content>
    </Layout>
  )
}
