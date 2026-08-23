# src/instance/

Flask's own default instance folder - `app.instance_path`, computed
automatically relative to `run.py` regardless of whether it's used.
Nothing in this app writes here today: config lives in `../configs/`,
credentials in `../secrets/`, and databases in `../data/`, each with an
explicit, deliberate path rather than Flask's implicit convention.

Kept only because Flask expects the folder to exist. If a future
dependency specifically requires `instance_relative_config=True` or
reads `app.instance_path` directly, it goes here - otherwise, prefer
one of the three folders above instead.
