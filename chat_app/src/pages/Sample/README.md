# pages/Sample/

A minimal working example page, kept around so the Overview picker always has
at least one real card to show and so new pages have something to copy.
URL prefix: `/sample`.

## Routes

- `GET /sample/` — static placeholder content.

## Permissions

None beyond being logged in (`PAGE_PERMISSION = None`).

## Templates

`sample.html` extends `__shared__/base.html` and includes the sidebar, like
any other non-Overview page.

Safe to delete once the project has real feature pages — remove this folder
and it disappears from routing and the Overview grid automatically.
