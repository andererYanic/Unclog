"""Connector layer (brief §9.3; decision 003). File uploads now, live tool connectors later."""

from .base import (
    Connector,
    CredentialProvider,
    DatasetInfo,
    WriteAction,
    WriteResult,
    available,
    register,
)
from .file_drop import FileDropConnector
from .sync import PullReport, pull

__all__ = [
    "Connector",
    "CredentialProvider",
    "DatasetInfo",
    "FileDropConnector",
    "PullReport",
    "WriteAction",
    "WriteResult",
    "available",
    "pull",
    "register",
]
