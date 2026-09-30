import { Tag } from 'antd'
import type { Label } from '../lib/labels'

export function LabelTag({ label }: { label: Label }) {
  return <Tag color={label.color}>{label.text}</Tag>
}
