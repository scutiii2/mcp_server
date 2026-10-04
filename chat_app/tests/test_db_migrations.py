import sqlalchemy as sa

from src.services.db_migrations import apply_additive_column_migrations


def _engine(tmp_path):
    return sa.create_engine(f"sqlite:///{tmp_path / 'migrations.db'}")


def test_adds_missing_not_null_column_with_static_default(tmp_path):
    engine = _engine(tmp_path)

    # Simulate a table created before the model gained a new column -
    # exactly what happened to accounts.email_verified in prod.
    old_metadata = sa.MetaData()
    accounts = sa.Table(
        "accounts", old_metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(80), nullable=False),
    )
    old_metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(accounts.insert().values(id=1, username="existing_user"))

    # The current model, one column ahead of what's on disk.
    new_metadata = sa.MetaData()
    sa.Table(
        "accounts", new_metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("email_verified", sa.Boolean, nullable=False, default=False),
    )

    added = apply_additive_column_migrations(engine, new_metadata)

    assert added == ["accounts.email_verified"]
    with engine.connect() as conn:
        row = conn.execute(sa.text("SELECT email_verified FROM accounts WHERE id = 1")).one()
        assert row.email_verified == 0


def test_no_op_when_schema_already_matches(tmp_path):
    engine = _engine(tmp_path)
    metadata = sa.MetaData()
    sa.Table(
        "accounts", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email_verified", sa.Boolean, nullable=False, default=False),
    )
    metadata.create_all(engine)

    added = apply_additive_column_migrations(engine, metadata)

    assert added == []


def test_brand_new_table_is_left_to_create_all(tmp_path):
    engine = _engine(tmp_path)
    # Nothing exists yet - create_all() is responsible for this table, not
    # the migration helper (which only patches tables that already exist).
    metadata = sa.MetaData()
    sa.Table(
        "some_new_table", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
    )

    added = apply_additive_column_migrations(engine, metadata)

    assert added == []
    inspector = sa.inspect(engine)
    assert "some_new_table" not in inspector.get_table_names()


def test_callable_default_adds_column_as_nullable_instead_of_failing(tmp_path):
    engine = _engine(tmp_path)

    old_metadata = sa.MetaData()
    sa.Table("events", old_metadata, sa.Column("id", sa.Integer, primary_key=True))
    old_metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO events (id) VALUES (1)"))

    new_metadata = sa.MetaData()
    sa.Table(
        "events", new_metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("created_at", sa.DateTime, nullable=False, default=lambda: "2026-01-01"),
    )

    # A callable default can't be expressed as a static SQL DEFAULT, so this
    # must not raise even though the model says NOT NULL - it degrades to
    # nullable rather than crashing startup.
    added = apply_additive_column_migrations(engine, new_metadata)

    assert added == ["events.created_at"]
    with engine.connect() as conn:
        row = conn.execute(sa.text("SELECT created_at FROM events WHERE id = 1")).one()
        assert row.created_at is None


def test_drop_retired_tables_drops_only_listed_existing_tables():
    import sqlalchemy as sa

    from src.services.db_migrations import drop_retired_tables

    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE capability_approvers (id INTEGER)"))
        conn.execute(sa.text("CREATE TABLE keepme (id INTEGER)"))

    assert drop_retired_tables(engine) == ["capability_approvers"]
    assert drop_retired_tables(engine) == []
    assert sa.inspect(engine).get_table_names() == ["keepme"]
