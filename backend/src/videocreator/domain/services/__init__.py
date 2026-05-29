"""Domain services — stateless, framework-free business logic.

These contain pure decision rules (no I/O) so they can be unit-tested without
mocks. Adapters in `infrastructure/` feed them data and act on their output.
"""
