# src/data/

SQLite databases, gitignored - regenerated (`db.create_all()` /
first-use `CREATE TABLE IF NOT EXISTS`) rather than seeded from source.

- **`app.db`** - the main SQLAlchemy database (`SQLALCHEMY_DATABASE_URI`,
  `secret_db.env`'s `DATABASE_URL` if set): accounts, roles,
  permissions, log entries, everything under `models/`.
- **`chats.db`** - chat history, kept separate from `app.db` on purpose
  - see `pages/Chat/README.md`'s "Persistence" note. Path overridable
    via `CHATS_DB_PATH`.

## Adding a new database file

Only if the new data is genuinely independent of `app.db`'s schema and
transaction boundary (the way chat history is) - most new data belongs
as a new model under `models/` instead, in `app.db`.
When a standalone file really is right, follow `chats_store.py`'s
pattern: a dedicated env var for the path (`BASE_DIR`-resolved, not
CWD-relative - see `run.py`'s `_resolve_sqlite_uri`), defaulting under
this folder.
