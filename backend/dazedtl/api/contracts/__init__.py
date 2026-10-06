"""The typed application API shared by the backend and the renderer."""


class ContractViolation(RuntimeError):
    """A value crossing the API boundary does not match its contract."""
