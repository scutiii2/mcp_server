# src/pages/__shared__/

The layout every page's templates extend - not a page itself, and
excluded from `pages/README.md`'s auto-discovery for exactly that
reason (no `__index__.py`, no blueprint).

- **`base.html`** - the outer shell (`<head>`, sidebar include, main
  content block) every page template extends.
- **`sidebar.html`** - left-nav: `nav_pages` links, the Overview logo/
  home link, and the account-menu include.
- **`account_menu.html`** - the avatar/username dropdown in the sidebar
  footer, rendering `account_menu_pages` (`Account`/`Admin`, deliberately
  excluded from `nav_pages` - see `pages/README.md`).
- **`shared.css`, `shared.js`** - styles and behavior common to every
  page (layout, the sidebar, the account menu). Page-specific styling
  stays in that page's own `styles.css`/`script.js`.
- **`error_403.html`, `error_429.html`** - rendered by `run.py`'s
  `@app.errorhandler(403)` / `@app.errorhandler(429)`.
- `logo.png`, if present - replaces the 🏠 emoji next to "Overview" in
  the sidebar (checked once at boot). Not committed by default.

## Adding to this folder

Add something here only when at least two pages need it. A style, a
script, or a template fragment only one page uses belongs in that
page's own folder instead - this folder is for what pages have in
common, not a general dumping ground. A new shared error page follows
`error_403.html`'s pattern: template here, `@app.errorhandler(...)` in
`run.py`.
