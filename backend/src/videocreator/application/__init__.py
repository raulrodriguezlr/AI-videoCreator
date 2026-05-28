"""Application layer — orchestrates domain ports to fulfill user-facing tasks.

Use cases are pure: they receive ports via constructor injection and contain
no FastAPI/CLI/SQLAlchemy specifics. They are reused by `interfaces/rest` and
`interfaces/cli` alike.
"""
