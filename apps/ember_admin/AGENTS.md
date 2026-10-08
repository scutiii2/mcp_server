# ember_admin

Project note: `Brain/Projects/ember_admin.md` in the Obsidian vault (`../../../../Brain/` from this folder), once it exists.

Vue 3 + TypeScript admin app for ember. It talks only to `ember_api` through the Vite `/api` proxy. Follow the `ember-design-system` and `ember-feature-scaffold` skills for UI and API conventions.

## Rules
- Admin and Analytics are owned by ember_admin; ember_web no longer has copies of these pages. The Usage line chart remains shared in style and behavior, with a copy in ember_web.
- Radius only through the `--radius-*` tokens, colors only through `style.css` tokens. `radiusScale.test.ts` enforces it.
- A switch that calls the server stays pending until the server answers; never show a state it did not confirm.
- Checks: `npx vue-tsc -b`, `npm test`, `npm run test:e2e`.
