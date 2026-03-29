"""lit package bootstrap."""

__all__ = ["LitBackendService", "Repository", "__version__"]

__version__ = "1.0.0"


def __getattr__(name: str):
    if name == "LitBackendService":
        from lit.backend_api import LitBackendService

        return LitBackendService
    if name == "Repository":
        from lit.repository import Repository

        return Repository
    raise AttributeError(name)
