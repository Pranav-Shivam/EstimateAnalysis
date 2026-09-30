# Frontend stack: versions and Tailwind 4 + Ant Design 6 compatibility

Researched 2026-09-30 for Phase 7. Versions come from `npm view <pkg> version` against the registry (verified). Web search results for React and antd were stale (React 19.0.0, antd 5.27) and were not used; the registry is the source of truth.

## Versions (latest stable, 2026-09-30)

| Package | Version |
|---|---|
| react, react-dom | 19.3.0 |
| vite | 8.3.1 |
| @vitejs/plugin-react | 6.1.1 |
| tailwindcss, @tailwindcss/vite | 4.3.3 |
| antd | 6.6.5 |
| @ant-design/icons | 6.3.4 |
| @ant-design/cssinjs | 2.1.2 |
| typescript | 7.0.2 |
| @tanstack/react-query | 5.104.0 |
| react-router | 8.4.0 |
| vitest | 5.0.2 |
| jsdom | 30.1.1 |
| @testing-library/react | 16.3.3 |
| @testing-library/user-event | 14.6.7 |
| @testing-library/jest-dom | 7.0.1 |
| openapi-typescript | 7.13.0 |
| openapi-fetch | 0.17.0 |
| eslint | 10.11.0 |
| typescript-eslint | 8.71.0 |

Engine constraints: Vite 8 and `@vitejs/plugin-react` 6 need Node `^20.19.0 || >=22.12.0`. Local Node is 24.16.0. `@vitejs/plugin-react` 6 peers on `vite ^8`. Vitest 5 peers on `vite ^6.4 || ^7 || ^8`. antd 6 peers on `react >=18`.

## Tailwind 4 with Ant Design 6 (verified against antd 6.5.0 docs via context7)

Ant Design's CSS-in-JS styles and Tailwind's preflight reset fight over the same selectors. The documented fix is cascade layers:

- Wrap the app in `StyleProvider` from `@ant-design/cssinjs` with the `layer` prop, so antd emits its styles inside an `@layer`.
- Declare the layer order in the global stylesheet before importing Tailwind: `@layer theme, base, antd, components, utilities;` then `@import "tailwindcss";`. Preflight (`base`) then sits below antd, and Tailwind utilities sit above it, so utilities can override antd.
- Wrap children in `ConfigProvider` inside `StyleProvider` so icon styles update.

Source: antd repo `docs/react/compatible-style.en-US.md` at tag 6.5.0.

Tailwind 4 with Vite: `npm install tailwindcss @tailwindcss/vite`, add `tailwindcss()` to the Vite `plugins` array, and `@import "tailwindcss"` in the stylesheet. No `tailwind.config.js` is needed. Source: tailwindcss.com/docs/installation.

## Not verified

- antd 6.6.5 behavior specifically (docs read were 6.5.0). Re-check `StyleProvider layer` against 6.6.5 at build time.
- TypeScript 7.0.2 compatibility with each tooling package (eslint, typescript-eslint, openapi-typescript). Confirm at install; pin TypeScript to the newest version the toolchain accepts if a peer conflict appears.
