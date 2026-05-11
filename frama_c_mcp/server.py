"""
Frama-C MCP Server with Dynamic Plugin Support

This module implements a Model Context Protocol (MCP) server that acts as an agent
for Frama-C formal verification framework. It supports dynamic plugin registration,
execution of Frama-C on user-provided C code, and structured result reporting.
"""

import json
import subprocess
import sys
from typing import Any, Optional
from dataclasses import dataclass, asdict
from pathlib import Path
import tempfile
import logging
from datetime import datetime

try:
    from mcp.server import Server
    from mcp.types import Tool, TextContent
except ImportError:
    # Fallback for testing without MCP installed
    Server = None
    Tool = None
    TextContent = None

logger = logging.getLogger(__name__)


@dataclass
class FramaCProofResult:
    """Structured proof result from Frama-C"""
    plugin: str
    status: str  # "success", "failed", "error", "timeout"
    proof_obligations: Optional[int] = None
    proven: Optional[int] = None
    unknown: Optional[int] = None
    failed: Optional[int] = None
    logs: str = ""
    error_message: Optional[str] = None
    timestamp: str = ""

    def to_json(self) -> dict:
        """Convert to JSON-serializable dict"""
        return asdict(self)


@dataclass
class ValidationStatus:
    """Overall validation and analysis status"""
    eva_status: Optional[str] = None
    rte_status: Optional[str] = None
    wp_status: Optional[str] = None
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    def to_json(self) -> dict:
        return {
            "eva_status": self.eva_status,
            "rte_status": self.rte_status,
            "wp_status": self.wp_status,
            "errors": self.errors,
        }


class FramaCPluginManager:
    """Manages Frama-C plugin discovery and execution"""

    def __init__(self, frama_c_path: str = "frama-c"):
        self.frama_c_path = frama_c_path
        self.plugins: dict[str, dict] = {}
        self.discover_plugins()

    def discover_plugins(self) -> None:
        """
        Discover available Frama-C plugins by parsing frama-c --plugins output
        """
        try:
            result = subprocess.run(
                [self.frama_c_path, "--plugins"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                logger.warning(f"Failed to discover plugins: {result.stderr}")
                # Register default plugins even if discovery fails
                self._register_default_plugins()
                return

            self._parse_plugins_output(result.stdout)
            logger.info(f"Discovered {len(self.plugins)} Frama-C plugins")

        except FileNotFoundError:
            logger.error(f"Frama-C not found at {self.frama_c_path}")
            self._register_default_plugins()
        except subprocess.TimeoutExpired:
            logger.error("Plugin discovery timed out")
            self._register_default_plugins()

    def _parse_plugins_output(self, output: str) -> None:
        """Parse frama-c --plugins output to extract plugin information"""
        lines = output.split("\n")
        current_plugin = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Try to identify plugin name (usually at the start of a line)
            if line.startswith("- "):
                # Format: - PluginName: Description
                parts = line[2:].split(":", 1)
                if len(parts) == 2:
                    plugin_name = parts[0].strip().lower()
                    description = parts[1].strip()
                    self.plugins[plugin_name] = {
                        "name": plugin_name,
                        "description": description,
                        "enabled": False,
                    }
                    current_plugin = plugin_name

        # If no plugins were parsed, register defaults
        if not self.plugins:
            self._register_default_plugins()

    def _register_default_plugins(self) -> None:
        """Register well-known Frama-C plugins as defaults"""
        default_plugins = {
            "wp": {
                "name": "wp",
                "description": "WP plugin for weakest precondition calculus and ACSL proof obligations",
                "enabled": False,
                "flags": ["-wp", "-wp-model", "typed"],
            },
            "eva": {
                "name": "eva",
                "description": "EVA (evolved value analysis) plugin for value analysis",
                "enabled": False,
                "flags": ["-eva"],
            },
            "rte": {
                "name": "rte",
                "description": "RTE plugin for runtime error annotation generation",
                "enabled": False,
                "flags": ["-rte"],
            },
            "slicing": {
                "name": "slicing",
                "description": "Program slicing plugin",
                "enabled": False,
                "flags": ["-slicing-level", "0"],
            },
            "scope": {
                "name": "scope",
                "description": "Scope plugin for scoping analysis",
                "enabled": False,
                "flags": ["-scope"],
            },
        }
        self.plugins.update(default_plugins)

    def get_plugins(self) -> list[dict]:
        """Get list of available plugins"""
        return list(self.plugins.values())

    def get_plugin_flags(self, plugin_names: list[str]) -> list[str]:
        """Get command-line flags for specified plugins"""
        flags = []
        for plugin_name in plugin_names:
            plugin_name_lower = plugin_name.lower()
            if plugin_name_lower in self.plugins:
                plugin = self.plugins[plugin_name_lower]
                if "flags" in plugin:
                    flags.extend(plugin["flags"])
        return flags

    def execute_plugin(
        self, plugin_name: str, c_code: str, plugin_flags: Optional[list[str]] = None
    ) -> FramaCProofResult:
        """
        Execute Frama-C plugin on provided C code

        Args:
            plugin_name: Name of the plugin to execute
            c_code: C source code to analyze
            plugin_flags: Additional flags to pass to frama-c

        Returns:
            FramaCProofResult with proof obligations, status, and logs
        """
        plugin_name_lower = plugin_name.lower()

        if plugin_name_lower not in self.plugins:
            return FramaCProofResult(
                plugin=plugin_name,
                status="error",
                error_message=f"Unknown plugin: {plugin_name}",
                timestamp=datetime.now().isoformat(),
            )

        # Write C code to temporary file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".c", delete=False, encoding="utf-8"
        ) as f:
            f.write(c_code)
            temp_file = f.name

        try:
            cmd = [self.frama_c_path, "-json-stream", temp_file]

            # Add plugin-specific flags
            plugin = self.plugins[plugin_name_lower]
            if "flags" in plugin:
                cmd.extend(plugin["flags"])

            # Add user-provided flags
            if plugin_flags:
                cmd.extend(plugin_flags)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            proof_result = self._parse_frama_c_output(
                plugin_name, result.stdout, result.stderr, result.returncode
            )
            proof_result.timestamp = datetime.now().isoformat()
            return proof_result

        except subprocess.TimeoutExpired:
            return FramaCProofResult(
                plugin=plugin_name,
                status="timeout",
                error_message="Frama-C execution timed out after 30 seconds",
                logs="",
                timestamp=datetime.now().isoformat(),
            )
        except Exception as e:
            logger.exception(f"Error executing {plugin_name}")
            return FramaCProofResult(
                plugin=plugin_name,
                status="error",
                error_message=str(e),
                logs="",
                timestamp=datetime.now().isoformat(),
            )
        finally:
            # Clean up temp file
            try:
                Path(temp_file).unlink()
            except Exception:
                pass

    def _parse_frama_c_output(
        self, plugin: str, stdout: str, stderr: str, returncode: int
    ) -> FramaCProofResult:
        """
        Parse Frama-C output and extract proof results

        Supports JSON stream output and legacy text output formats
        """
        proof_obligations = None
        proven = None
        unknown = None
        failed = None
        logs = stdout + stderr

        # Try to parse JSON stream output (newer Frama-C versions)
        if stdout.strip():
            try:
                for line in stdout.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        # Extract proof statistics from JSON
                        if isinstance(data, dict):
                            if "goals" in data:
                                proof_obligations = data["goals"].get(
                                    "total", proof_obligations
                                )
                                proven = data["goals"].get("proved", proven)
                                unknown = data["goals"].get("unknown", unknown)
                                failed = data["goals"].get("failed", failed)
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                logger.debug(f"Failed to parse JSON output: {e}")

        # Parse text output for legacy formats
        if "Proof" in stderr or "proof" in stdout.lower():
            # Extract proof statistics from text output
            import re

            # Look for patterns like "123 proof obligations"
            if match := re.search(r"(\d+)\s+proof\s+obligations", stdout + stderr):
                proof_obligations = int(match.group(1))

            # Look for patterns like "Proved: 45"
            if match := re.search(
                r"(?:proved|proven|Proved):\s*(\d+)", stdout + stderr, re.IGNORECASE
            ):
                proven = int(match.group(1))

        status = "success" if returncode == 0 else "failed"
        if returncode not in (0, 1):
            status = "error"

        return FramaCProofResult(
            plugin=plugin,
            status=status,
            proof_obligations=proof_obligations,
            proven=proven,
            unknown=unknown,
            failed=failed,
            logs=logs,
            error_message=stderr if returncode != 0 else None,
        )


class FramaCMCPServer:
    """MCP Server for Frama-C formal verification"""

    def __init__(self, frama_c_path: str = "frama-c"):
        self.plugin_manager = FramaCPluginManager(frama_c_path)
        self.server = Server("frama-c-mcp") if Server else None
        self._register_tools()

    def _register_tools(self) -> None:
        """Register MCP tools for Frama-C operations"""
        if not self.server:
            logger.warning("MCP Server not available - running in test mode")
            return

        # Register list_plugins tool
        @self.server.list_tools()
        def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="list_plugins",
                    description="List all available Frama-C plugins",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                ),
                Tool(
                    name="execute_wp",
                    description="Execute WP (weakest precondition) plugin for proof obligation checking",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "c_code": {
                                "type": "string",
                                "description": "Annotated C code with ACSL specifications",
                            },
                            "wp_model": {
                                "type": "string",
                                "enum": ["typed", "guards", "cint", "rte"],
                                "description": "WP computation model",
                            },
                        },
                        "required": ["c_code"],
                    },
                ),
                Tool(
                    name="execute_eva",
                    description="Execute EVA (evolved value analysis) plugin for value analysis",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "c_code": {
                                "type": "string",
                                "description": "C code to analyze",
                            },
                        },
                        "required": ["c_code"],
                    },
                ),
                Tool(
                    name="execute_rte",
                    description="Execute RTE (runtime error) plugin for runtime error detection",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "c_code": {
                                "type": "string",
                                "description": "C code to analyze",
                            },
                        },
                        "required": ["c_code"],
                    },
                ),
                Tool(
                    name="execute_combined",
                    description="Execute multiple plugins on C code with structured results",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "c_code": {
                                "type": "string",
                                "description": "C code to analyze",
                            },
                            "plugins": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of plugins to execute (wp, eva, rte, etc.)",
                            },
                        },
                        "required": ["c_code", "plugins"],
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            if name == "list_plugins":
                return self._handle_list_plugins()
            elif name == "execute_wp":
                return self._handle_execute_wp(arguments)
            elif name == "execute_eva":
                return self._handle_execute_eva(arguments)
            elif name == "execute_rte":
                return self._handle_execute_rte(arguments)
            elif name == "execute_combined":
                return self._handle_execute_combined(arguments)
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

    def _handle_list_plugins(self) -> list:
        """Handle list_plugins tool call"""
        plugins = self.plugin_manager.get_plugins()
        response = {
            "available_plugins": plugins,
            "count": len(plugins),
        }
        return [
            TextContent(type="text", text=json.dumps(response, indent=2))
        ] if TextContent else []

    def _handle_execute_wp(self, arguments: dict) -> list:
        """Handle execute_wp tool call"""
        c_code = arguments.get("c_code", "")
        wp_model = arguments.get("wp_model", "typed")

        flags = ["-wp-model", wp_model]
        result = self.plugin_manager.execute_plugin("wp", c_code, flags)

        response = {
            "result": result.to_json(),
            "validation_status": ValidationStatus(wp_status=result.status).to_json(),
        }
        return [
            TextContent(type="text", text=json.dumps(response, indent=2))
        ] if TextContent else []

    def _handle_execute_eva(self, arguments: dict) -> list:
        """Handle execute_eva tool call"""
        c_code = arguments.get("c_code", "")
        result = self.plugin_manager.execute_plugin("eva", c_code)

        response = {
            "result": result.to_json(),
            "validation_status": ValidationStatus(eva_status=result.status).to_json(),
        }
        return [
            TextContent(type="text", text=json.dumps(response, indent=2))
        ] if TextContent else []

    def _handle_execute_rte(self, arguments: dict) -> list:
        """Handle execute_rte tool call"""
        c_code = arguments.get("c_code", "")
        result = self.plugin_manager.execute_plugin("rte", c_code)

        response = {
            "result": result.to_json(),
            "validation_status": ValidationStatus(rte_status=result.status).to_json(),
        }
        return [
            TextContent(type="text", text=json.dumps(response, indent=2))
        ] if TextContent else []

    def _handle_execute_combined(self, arguments: dict) -> list:
        """Handle execute_combined tool call with multiple plugins"""
        c_code = arguments.get("c_code", "")
        plugins = arguments.get("plugins", [])

        results = {}
        validation_status = ValidationStatus()

        for plugin_name in plugins:
            result = self.plugin_manager.execute_plugin(plugin_name, c_code)
            results[plugin_name] = result.to_json()

            # Update validation status
            if plugin_name.lower() == "wp":
                validation_status.wp_status = result.status
            elif plugin_name.lower() == "eva":
                validation_status.eva_status = result.status
            elif plugin_name.lower() == "rte":
                validation_status.rte_status = result.status

            if result.error_message:
                validation_status.errors.append(
                    f"{plugin_name}: {result.error_message}"
                )

        response = {
            "results": results,
            "validation_status": validation_status.to_json(),
            "plugins_executed": len(results),
        }
        return [
            TextContent(type="text", text=json.dumps(response, indent=2))
        ] if TextContent else []

    def run(self, host: str = "localhost", port: int = 8000) -> None:
        """Run the MCP server"""
        if not self.server:
            raise RuntimeError("MCP Server not available")
        logger.info(f"Starting Frama-C MCP Server on {host}:{port}")
        self.server.run(host, port)


def main():
    """Entry point for the Frama-C MCP server"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        server = FramaCMCPServer()
        server.run()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
        sys.exit(0)
    except Exception as e:
        logger.exception("Server error")
        sys.exit(1)


if __name__ == "__main__":
    main()
