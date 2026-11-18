"""Implementations of the internal `Executor` interface (`utux.interfaces.executor`).

`scripted` plays back a script and runs nothing; it is for tests. The
hardened Docker executor is task M1-07. Implementations depend only on the
interfaces, the schemas and `utux.workspace`, never on each other.
"""
