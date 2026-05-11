"""Frama-C MCP Server - Model Context Protocol integration for Frama-C formal verification"""

__version__ = "0.1.0"
__author__ = "Sabitra"
__description__ = "MCP Server for Frama-C formal verification framework with dynamic plugin support"

from .server import (
    FramaCMCPServer,
    FramaCPluginManager,
    FramaCProofResult,
    ValidationStatus,
)

__all__ = [
    "FramaCMCPServer",
    "FramaCPluginManager",
    "FramaCProofResult",
    "ValidationStatus",
]
