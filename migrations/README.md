The first migration intentionally delegates table definitions to the SQLAlchemy metadata
so SQLite and PostgreSQL share the same domain contract. Future migrations must be
additive and keep Artifact/RunEvent history append-only.
