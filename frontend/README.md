# frontend — procurement-allocator

React + TypeScript + Vite. Routing via `react-router-dom`. Design tokens live in
`src/styles/tokens.css`, sourced from `docs/design/README.md` → "Design Tokens"
(canon palette, screens 2–3). See root `CLAUDE.md` for how `docs/design/` and
`docs/ui-reference.md` relate.

## Setup

Create `.env` in this directory (gitignored) with:

```
VITE_API_BASE_URL=http://localhost:8000
```

If unset, the API client falls back to `http://localhost:8000`.

## Structure

```
src/
  api/        — typed fetch client for the backend (suppliers, materials, prices, allocation)
  layout/     — AppLayout: topbar + nav shared by all screens
  routes/     — one page component per route (currently stubs for the 3 MVP screens)
  styles/     — design tokens + global stylesheet
  test/       — vitest setup
```

## Commands

```
npm run dev
npm run lint    # oxlint
npm run test    # vitest run
npm run build   # tsc -b && vite build
```

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
