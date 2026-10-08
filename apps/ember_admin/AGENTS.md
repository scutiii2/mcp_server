# ember_admin

Project note: `Brain/Projects/ember_admin.md` in the Obsidian vault (`../../../../Brain/` from this folder), once it exists.

Vue 3 + TypeScript admin app for ember. It talks only to `ember_api` through the Vite `/api` proxy. Follow the `ember-design-system` and `ember-feature-scaffold` skills for UI and API conventions.

## Rules
- `src/views/AdminView.vue`, `AnalyticsView.vue` and the components they use are copies of `ember_web`'s. A fix to one is usually needed in the other until the `ember_web` copy is removed.
- Radius only through the `--radius-*` tokens, colors only through `style.css` tokens. `radiusScale.test.ts` enforces it.
- A switch that calls the server stays pending until the server answers; never show a state it did not confirm.
- Checks: `npx vue-tsc -b`, `npm test`, `npm run test:e2e`.
