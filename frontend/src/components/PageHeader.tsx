import type { ReactNode } from 'react'

interface Props {
  title: ReactNode
  description?: ReactNode
  extra?: ReactNode
}

export function PageHeader({ title, description, extra }: Props) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="m-0 text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {description && <p className="m-0 text-slate-500">{description}</p>}
      </div>
      {extra}
    </div>
  )
}
