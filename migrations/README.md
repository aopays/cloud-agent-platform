# Database migrations

The runnable P0 starts with a local repository adapter so the complete workflow can
be demonstrated without external infrastructure. PostgreSQL remains the target
production store. Add versioned migrations here when the PostgreSQL adapter is
introduced; shared lifecycle semantics must remain compatible with
`src/shared/contracts.py`.
