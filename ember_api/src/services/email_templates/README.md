# email_templates/

Plain-text bodies for `SmtpEmailSender` (`../email_service.py`).
`string.Template` files: `$name` marks a placeholder. A missing value
raises `KeyError`.

| Template | Placeholders |
| --- | --- |
| `invite` | `code`, `expires_at` |
| `email_verification` | `code`, `expires_at` |

Do not add the auto-generated footer here: `_send` appends it to every message.
To add one: drop `<name>.txt` here, list it above, call `render_template("<name>", ...)`.
