"""
Unit tests for Frama-C MCP Server

Tests cover plugin discovery, execution, result parsing, and error handling.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

from frama_c_mcp.server import (
    FramaCPluginManager,
    FramaCProofResult,
    ValidationStatus,
    FramaCMCPServer,
)


class TestFramaCProofResult:
    """Test FramaCProofResult dataclass"""

    def test_proof_result_creation(self):
        """Test basic proof result creation"""
        result = FramaCProofResult(
            plugin="wp",
            status="success",
            proof_obligations=10,
            proven=8,
            unknown=2,
            failed=0,
            logs="test logs",
            timestamp=datetime.now().isoformat(),
        )

        assert result.plugin == "wp"
        assert result.status == "success"
        assert result.proof_obligations == 10
        assert result.proven == 8

    def test_proof_result_to_json(self):
        """Test conversion to JSON-serializable dict"""
        result = FramaCProofResult(
            plugin="eva",
            status="failed",
            error_message="test error",
            timestamp=datetime.now().isoformat(),
        )

        json_dict = result.to_json()
        assert isinstance(json_dict, dict)
        assert json_dict["plugin"] == "eva"
        assert json_dict["status"] == "failed"
        assert json_dict["error_message"] == "test error"


class TestValidationStatus:
    """Test ValidationStatus dataclass"""

    def test_validation_status_creation(self):
        """Test ValidationStatus creation"""
        status = ValidationStatus(
            eva_status="success",
            rte_status="success",
            wp_status="failed",
            errors=["WP timeout"],
        )

        assert status.eva_status == "success"
        assert status.rte_status == "success"
        assert status.wp_status == "failed"
        assert len(status.errors) == 1

    def test_validation_status_to_json(self):
        """Test conversion to JSON format"""
        status = ValidationStatus(
            eva_status="success",
            errors=["Error 1", "Error 2"],
        )

        json_dict = status.to_json()
        assert isinstance(json_dict, dict)
        assert json_dict["eva_status"] == "success"
        assert len(json_dict["errors"]) == 2

    def test_validation_status_default_errors(self):
        """Test default empty errors list"""
        status = ValidationStatus()
        assert status.errors == []


class TestFramaCPluginManager:
    """Test FramaCPluginManager"""

    def test_plugin_manager_initialization(self):
        """Test plugin manager initialization"""
        manager = FramaCPluginManager(frama_c_path="frama-c")
        assert manager.frama_c_path == "frama-c"
        assert isinstance(manager.plugins, dict)

    def test_default_plugins_registered(self):
        """Test that default plugins are registered when discovery fails"""
        manager = FramaCPluginManager(frama_c_path="frama-c")
        
        # Should have at least default plugins
        assert len(manager.plugins) > 0
        assert "wp" in manager.plugins
        assert "eva" in manager.plugins
        assert "rte" in manager.plugins

    def test_get_plugins(self):
        """Test getting list of plugins"""
        manager = FramaCPluginManager()
        plugins = manager.get_plugins()

        assert isinstance(plugins, list)
        assert len(plugins) > 0
        assert all("name" in p for p in plugins)
        assert all("description" in p for p in plugins)

    def test_get_plugin_flags(self):
        """Test retrieving plugin flags"""
        manager = FramaCPluginManager()
        flags = manager.get_plugin_flags(["wp", "eva"])

        assert isinstance(flags, list)
        # Should have flags for wp and eva
        assert len(flags) > 0

    def test_get_plugin_flags_nonexistent(self):
        """Test getting flags for non-existent plugin"""
        manager = FramaCPluginManager()
        flags = manager.get_plugin_flags(["nonexistent"])

        # Should return empty list for unknown plugin
        assert isinstance(flags, list)

    @patch("subprocess.run")
    def test_execute_plugin_success(self, mock_run):
        """Test successful plugin execution"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Proof obligations: 10\nProved: 8",
            stderr="",
        )

        manager = FramaCPluginManager()
        result = manager.execute_plugin("wp", "int x = 5;")

        assert result.plugin == "wp"
        assert result.status == "success"
        assert result.error_message is None

    @patch("subprocess.run")
    def test_execute_plugin_timeout(self, mock_run):
        """Test plugin execution timeout"""
        mock_run.side_effect = TimeoutError()

        manager = FramaCPluginManager()
        
        with patch("subprocess.run") as mock_subprocess:
            mock_subprocess.side_effect = TimeoutError()
            result = manager.execute_plugin("wp", "int x = 5;")

            assert result.status == "timeout"
            assert "timed out" in result.error_message.lower()

    @patch("subprocess.run")
    def test_execute_plugin_unknown_plugin(self, mock_run):
        """Test executing unknown plugin"""
        manager = FramaCPluginManager()
        result = manager.execute_plugin("unknown_plugin", "int x = 5;")

        assert result.status == "error"
        assert "Unknown plugin" in result.error_message

    @patch("subprocess.run")
    def test_parse_frama_c_output_success(self, mock_run):
        """Test parsing successful Frama-C output"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="10 proof obligations\nProved: 8\n",
            stderr="",
        )

        manager = FramaCPluginManager()
        result = manager.execute_plugin("wp", "int x;")

        assert result.status == "success"

    @patch("subprocess.run")
    def test_parse_frama_c_output_failure(self, mock_run):
        """Test parsing failed Frama-C output"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Syntax error in input file",
        )

        manager = FramaCPluginManager()
        result = manager.execute_plugin("wp", "invalid code")

        assert result.status == "failed"
        assert result.error_message is not None

    def test_register_default_plugins(self):
        """Test default plugin registration"""
        manager = FramaCPluginManager()
        manager._register_default_plugins()

        assert "wp" in manager.plugins
        assert "eva" in manager.plugins
        assert "rte" in manager.plugins
        assert "slicing" in manager.plugins
        assert "scope" in manager.plugins

        # Check WP plugin structure
        wp = manager.plugins["wp"]
        assert wp["name"] == "wp"
        assert "description" in wp
        assert "flags" in wp

    @patch("subprocess.run")
    def test_parse_plugins_output(self, mock_run):
        """Test parsing frama-c --plugins output"""
        plugins_output = """
        - WP: Weakest precondition calculus
        - EVA: Evolved value analysis
        - RTE: Runtime error detection
        """

        manager = FramaCPluginManager()
        manager._parse_plugins_output(plugins_output)

        # Parser should extract plugin names
        assert len(manager.plugins) > 0


class TestFramaCMCPServer:
    """Test FramaCMCPServer"""

    def test_server_initialization(self):
        """Test MCP server initialization"""
        # Server initialization should not fail
        server = FramaCMCPServer()
        assert server.plugin_manager is not None

    def test_server_with_custom_path(self):
        """Test server with custom Frama-C path"""
        server = FramaCMCPServer(frama_c_path="/custom/path/frama-c")
        assert server.plugin_manager.frama_c_path == "/custom/path/frama-c"

    def test_handle_list_plugins(self):
        """Test list_plugins handler"""
        server = FramaCMCPServer()
        result = server._handle_list_plugins()

        # Result should be list (or empty if TextContent not available)
        assert isinstance(result, list)

    def test_handle_execute_wp(self):
        """Test execute_wp handler"""
        server = FramaCMCPServer()
        c_code = "int x = 5;"
        
        result = server._handle_execute_wp({"c_code": c_code})
        assert isinstance(result, list)

    def test_handle_execute_eva(self):
        """Test execute_eva handler"""
        server = FramaCMCPServer()
        c_code = "int x = 5;"
        
        result = server._handle_execute_eva({"c_code": c_code})
        assert isinstance(result, list)

    def test_handle_execute_rte(self):
        """Test execute_rte handler"""
        server = FramaCMCMCPServer()
        c_code = "int x = 5;"
        
        result = server._handle_execute_rte({"c_code": c_code})
        assert isinstance(result, list)

    def test_handle_execute_combined(self):
        """Test execute_combined handler"""
        server = FramaCMCPServer()
        c_code = "int x = 5;"
        
        result = server._handle_execute_combined({
            "c_code": c_code,
            "plugins": ["wp", "eva"]
        })
        assert isinstance(result, list)


class TestIntegration:
    """Integration tests"""

    def test_end_to_end_simple_code(self):
        """Test end-to-end execution with simple C code"""
        manager = FramaCPluginManager()
        
        c_code = """
        int add(int a, int b) {
            return a + b;
        }
        """
        
        # This should not crash
        result = manager.execute_plugin("eva", c_code)
        assert result.plugin == "eva"
        assert result.status in ["success", "failed", "error", "timeout"]

    def test_end_to_end_multiple_plugins(self):
        """Test executing multiple plugins on same code"""
        manager = FramaCPluginManager()
        
        c_code = """
        int divide(int a, int b) {
            return a / b;
        }
        """
        
        for plugin in ["eva", "rte"]:
            result = manager.execute_plugin(plugin, c_code)
            assert result.plugin == plugin
            assert result.status in ["success", "failed", "error", "timeout"]


class TestEdgeCases:
    """Test edge cases and error conditions"""

    def test_empty_c_code(self):
        """Test with empty C code"""
        manager = FramaCPluginManager()
        result = manager.execute_plugin("eva", "")
        
        # Should handle empty code gracefully
        assert result.plugin == "eva"
        assert result.status in ["success", "failed", "error", "timeout"]

    def test_very_large_c_code(self):
        """Test with large C code"""
        manager = FramaCPluginManager()
        
        # Generate large C code
        large_code = "int x = 0;\n" * 10000
        result = manager.execute_plugin("eva", large_code)
        
        assert result.plugin == "eva"
        assert result.status in ["success", "failed", "error", "timeout"]

    def test_invalid_plugin_name(self):
        """Test with invalid plugin name"""
        manager = FramaCPluginManager()
        result = manager.execute_plugin("invalid_plugin_xyz", "int x;")
        
        assert result.status == "error"
        assert "Unknown plugin" in result.error_message

    def test_special_characters_in_code(self):
        """Test with special characters in C code"""
        manager = FramaCPluginManager()
        
        c_code = """
        char *str = "Hello\\nWorld\\t!";
        /* Special chars: @#$%^&*() */
        """
        
        result = manager.execute_plugin("eva", c_code)
        assert result.plugin == "eva"
        assert result.status in ["success", "failed", "error", "timeout"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
