# email_templates/

HTML body templates for `send_email()`. Plain `string.Template` files:
`$name` marks a placeholder. Render with
`email_render.render_email_template("<file stem>", name=value, ...)`.

- Every value is HTML-escaped, except names ending in `_html`, which are
  inserted as-is (use for markup the caller built itself).
- A missing placeholder value raises `KeyError`; an extra one is ignored.
- Do not add the auto-generated footer or the `[EMBER | alias]` subject
  prefix here: `send_email()` adds both to every message.

| Template | Placeholders |
| --- | --- |
| `notification` | `title`, `message`, `details_html` |
| `approval` | `title`, `message`, `action`, `approve_url` |

To add one: drop `<name>.html` here, list it in the table above.
