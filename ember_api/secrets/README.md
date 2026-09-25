# secrets

Real `secret_*.env` files are gitignored; each has a committed `.example`
twin that is copied on first run if the real file is missing.

- `secret_bootstrap_admin.env` - username/email/password of the first
  admin account (see the example file).
