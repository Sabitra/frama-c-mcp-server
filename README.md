# Frama-C MCP Server

A Model Context Protocol (MCP) server implementation for the Frama-C formal verification framework. This server enables dynamic plugin discovery, C code analysis, and structured proof obligation checking through a standardized MCP interface.

## Features

- **Dynamic Plugin Discovery**: Automatically discovers available Frama-C plugins and their capabilities
- **Multi-Plugin Support**: Execute WP (weakest precondition), EVA (value analysis), RTE (runtime errors), and more
- **Structured Results**: Returns proof obligations, verification status, and detailed logs in JSON format
- **Error Handling**: Graceful timeout and error handling with informative messages
- **ACSL Support**: Full support for ACSL (ANSI/ISO C Specification Language) annotations
- **Flexible Configuration**: Customize plugin flags and execution parameters

## Installation

### Prerequisites

- Python 3.9+
- Frama-C (latest version recommended)
- MCP library

### Setup

```bash
# Clone the repository
git clone https://github.com/Sabitra/frama-c-mcp-server.git
cd frama-c-mcp-server

# Install dependencies
pip install -r requirements.txt

# Optional: Install frama-c if not already installed
# On Ubuntu/Debian:
sudo apt-get install frama-c

# On macOS with Homebrew:
brew install frama-c
```

## Quick Start

### Running as MCP Server

```python
from frama_c_mcp import FramaCMCPServer

# Initialize server
server = FramaCMCPServer()

# Run on localhost:8000
server.run(host="localhost", port=8000)
```

### Programmatic Usage

```python
from frama_c_mcp import FramaCPluginManager

# Create plugin manager
manager = FramaCPluginManager()

# List available plugins
plugins = manager.get_plugins()
for plugin in plugins:
    print(f"{plugin['name']}: {plugin['description']}")

# Execute a plugin
c_code = """
int divide(int a, int b) {
    return a / b;
}
"""

result = manager.execute_plugin("rte", c_code)
print(f"Status: {result.status}")
print(f"Proof Obligations: {result.proof_obligations}")
```

## MCP Tools

### `list_plugins`

Lists all available Frama-C plugins on the system.

**Request:**
```json
{
  "name": "list_plugins"
}
```

**Response:**
```json
{
  "available_plugins": [
    {
      "name": "wp",
      "description": "WP plugin for weakest precondition calculus...",
      "enabled": false
    },
    {
      "name": "eva",
      "description": "EVA (evolved value analysis) plugin...",
      "enabled": false
    }
  ],
  "count": 5
}
```

### `execute_wp`

Execute WP (weakest precondition) plugin for proof obligation analysis.

**Parameters:**
- `c_code` (string): Annotated C code with ACSL specifications
- `wp_model` (string, optional): Computation model - `typed`, `guards`, `cint`, or `rte` (default: `typed`)

**Example:**
```python
c_code = """
/*@ requires x >= 0;
    ensures \result >= 0;
*/
int square(int x) {
    return x * x;
}
"""

result = server.execute_wp(c_code, wp_model="typed")
```

### `execute_eva`

Execute EVA (evolved value analysis) plugin for value analysis.

**Parameters:**
- `c_code` (string): C code to analyze

**Example:**
```python
c_code = """
int buffer[10];

void initialize() {
    for (int i = 0; i < 10; i++) {
        buffer[i] = i;
    }
}
"""

result = server.execute_eva(c_code)
```

### `execute_rte`

Execute RTE (runtime error) plugin for runtime error detection.

**Parameters:**
- `c_code` (string): C code to analyze

**Example:**
```python
c_code = """
int divide(int a, int b) {
    return a / b;  // potential division by zero
}
"""

result = server.execute_rte(c_code)
```

### `execute_combined`

Execute multiple plugins on C code with consolidated results.

**Parameters:**
- `c_code` (string): C code to analyze
- `plugins` (array): List of plugin names to execute

**Example:**
```python
c_code = """
/*@ requires n > 0;
    ensures \result > 0;
*/
int factorial(int n) {
    int result = 1;
    for (int i = 2; i <= n; i++) {
        result *= i;
    }
    return result;
}
"""

result = server.execute_combined(c_code, plugins=["wp", "eva", "rte"])
```

## Result Structure

### FramaCProofResult

```python
@dataclass
class FramaCProofResult:
    plugin: str                  # Name of executed plugin
    status: str                  # "success", "failed", "error", "timeout"
    proof_obligations: int       # Total proof obligations generated
    proven: int                  # Number of proven obligations
    unknown: int                 # Number of unknown obligations
    failed: int                  # Number of failed obligations
    logs: str                    # Full output logs
    error_message: str           # Error message if any
    timestamp: str               # Execution timestamp
```

### ValidationStatus

```python
@dataclass
class ValidationStatus:
    eva_status: str              # EVA plugin execution status
    rte_status: str              # RTE plugin execution status
    wp_status: str               # WP plugin execution status
    errors: list[str]            # List of error messages
```

## Supported Plugins

| Plugin | Name | Purpose |
|--------|------|---------|
| **WP** | Weakest Precondition | ACSL proof obligation checking |
| **EVA** | Evolved Value Analysis | Value range analysis |
| **RTE** | Runtime Error Detection | Identifies potential runtime errors |
| **Slicing** | Program Slicing | Code dependency analysis |
| **Scope** | Scope Analysis | Scoping analysis |

## Configuration

### Custom Frama-C Path

```python
# If frama-c is not in PATH
manager = FramaCPluginManager(frama_c_path="/opt/frama-c/bin/frama-c")
```

### Plugin Flags

```python
# Execute with custom flags
custom_flags = ["-wp-timeout", "30", "-wp-depth", "5"]
result = manager.execute_plugin("wp", c_code, plugin_flags=custom_flags)
```

## Error Handling

The server handles various error conditions gracefully:

- **Frama-C Not Found**: Falls back to well-known plugin list
- **Plugin Timeout**: Returns timeout status after 30 seconds
- **Invalid C Code**: Returns error status with error message
- **Execution Errors**: Captures and returns stderr output

```python
result = manager.execute_plugin("wp", invalid_code)
if result.status == "error":
    print(f"Error: {result.error_message}")
    print(f"Logs: {result.logs}")
```

## Architecture

```
┌─────────────────────────────────────┐
│    MCP Client / Claude              │
└────────────┬────────────────────────┘
             │ MCP Protocol
             │
┌────────────▼────────────────────────┐
│    FramaCMCPServer                  │
│  - Tool Registration                │
│  - Request Routing                  │
└────────────┬────────────────────────┘
             │
┌────────────▼────────────────────────┐
│    FramaCPluginManager              │
│  - Plugin Discovery                 │
│  - Plugin Execution                 │
│  - Output Parsing                   │
└────────────┬────────────────────────┘
             │
┌────────────▼────────────────────────┐
│    Frama-C (Command Line)           │
│  - WP Plugin                        │
│  - EVA Plugin                       │
│  - RTE Plugin                       │
│  - Other Plugins                    │
└─────────────────────────────────────┘
```

## Troubleshooting

### "Frama-C not found"

Ensure Frama-C is installed and in your PATH:
```bash
which frama-c
frama-c -version
```

Or specify the path explicitly:
```python
manager = FramaCPluginManager(frama_c_path="/path/to/frama-c")
```

### "Plugin discovery timed out"

This may occur with large plugin lists or slow systems. The server will fall back to well-known plugins.

### "Execution timeout"

Default timeout is 30 seconds. For longer analyses, increase the timeout or break code into smaller pieces:

```python
# Check available timeout settings
result = manager.execute_plugin("wp", code, plugin_flags=["-wp-timeout", "60"])
```

### Invalid ACSL annotations

Verify ACSL syntax matches Frama-C standards. See [ACSL Documentation](https://frama-c.com/html/acsl.html)

## Development

### Running Tests

```bash
pytest tests/
```

### Adding New Plugins

To support additional Frama-C plugins, extend the default plugin list in `FramaCPluginManager._register_default_plugins()`:

```python
new_plugin = {
    "name": "my_plugin",
    "description": "My custom plugin",
    "enabled": False,
    "flags": ["-my-plugin", "-my-flag"],
}
self.plugins.update({"my_plugin": new_plugin})
```

## License

MIT

## Contributing

Contributions welcome! Please open an issue or pull request.

## References

- [Frama-C Documentation](https://frama-c.com/)
- [ACSL Specification](https://frama-c.com/html/acsl.html)
- [MCP Specification](https://modelcontextprotocol.io/)
