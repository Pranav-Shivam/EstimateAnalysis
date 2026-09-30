import type { ThemeConfig } from 'antd'

// System font stack: the app runs offline in docker, so no web font is fetched.
const FONT = 'Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'

export const theme: ThemeConfig = {
  token: {
    colorPrimary: '#4f46e5',
    colorInfo: '#4f46e5',
    colorBgLayout: '#f8fafc',
    colorBorderSecondary: '#e2e8f0',
    colorTextSecondary: '#64748b',
    borderRadius: 8,
    fontFamily: FONT,
  },
  components: {
    Card: { headerFontSize: 15 },
    Table: { headerBg: '#f8fafc', headerColor: '#475569', rowHoverBg: '#f1f5f9' },
    Layout: { headerBg: '#ffffff', headerPadding: '0 24px', headerHeight: 60 },
    Menu: { itemBg: 'transparent', horizontalItemSelectedColor: '#4f46e5' },
  },
}
