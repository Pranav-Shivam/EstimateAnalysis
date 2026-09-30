import Markdown from 'react-markdown'

// Model-written text (judge rationale, flagged facts, agent notes) can carry inline markdown such as **bold** or
// `code`. Rendering it keeps raw asterisks off the screen; only inline elements are allowed, anything else is
// unwrapped to its text, and react-markdown never injects raw HTML.
const INLINE = ['p', 'strong', 'em', 'code', 'del']

export function RichText({ children }: { children: string }) {
  return (
    <Markdown
      allowedElements={INLINE}
      unwrapDisallowed
      components={{
        p: ({ children: inner }) => <>{inner}</>,
        code: ({ children: inner }) => <code className="rounded bg-black/5 px-1 font-mono text-[0.9em]">{inner}</code>,
      }}
    >
      {children}
    </Markdown>
  )
}
