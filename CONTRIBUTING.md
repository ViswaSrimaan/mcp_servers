# 🤝 Contributing to Laptop Assistant MCP Server

Thank you for your interest in contributing! This guide outlines the rules and conventions every contributor must follow to keep the codebase consistent, secure, and high-quality.

---

## 📋 Table of Contents

- [Code of Conduct](#-code-of-conduct)
- [Getting Started](#-getting-started)
- [Development Setup](#-development-setup)
- [Project Structure](#-project-structure)
- [Contribution Workflow](#-contribution-workflow)
- [Coding Standards](#-coding-standards)
- [Adding New Tools](#-adding-new-tools)
- [Security Guidelines](#-security-guidelines)
- [Testing Requirements](#-testing-requirements)
- [Commit & PR Conventions](#-commit--pr-conventions)
- [What We Accept](#-what-we-accept)
- [Need Help?](#-need-help)

---

## 📜 Code of Conduct

- Be **respectful** and **constructive** in all interactions.
- No harassment, discrimination, or toxic behavior of any kind.
- Focus feedback on the **code**, not the person.
- Help new contributors learn — we were all beginners once.

---

## 🚀 Getting Started

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```powershell
   git clone https://github.com/<your-username>/mcp_servers.git
   cd mcp_servers
   ```
3. **Add the upstream remote** so you can stay in sync:
   ```powershell
   git remote add upstream https://github.com/ViswaSrimaan/mcp_servers.git
   ```

---

## 🛠️ Development Setup

### Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.10+ |
| Windows | 10 / 11 |
| Git | Latest |

### Install Dependencies

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install mcp psutil httpx beautifulsoup4 pyperclip Pillow duckduckgo-search
```

### Verify the Server Starts

```powershell
python server.py
```

You should see:  
`Laptop Assistant MCP server initialized with all tools registered.`

---

## 📁 Project Structure

```
mcp_servers/
├── server.py                  # Entry point — registers all tool modules
├── src/
│   ├── __init__.py
│   ├── safety.py              # Two-phase confirmation token system
│   ├── security_config.py     # Security hardening (path, URL, execution)
│   └── tools/
│       ├── __init__.py
│       ├── system_tools.py    # System info, commands, processes
│       ├── file_tools.py      # File management operations
│       ├── web_tools.py       # Web search, fetch, download
│       ├── app_tools.py       # Application management (winget)
│       └── utility_tools.py   # Clipboard, screenshots, open apps
├── test_security.py           # Security test suite
├── SECURITY_REPORT.md         # Security audit report
└── README.md
```

> [!IMPORTANT]
> **Do NOT modify the project structure** without prior discussion in a GitHub issue.

---

## 🔄 Contribution Workflow

1. **Create a branch** from `main` with a descriptive name:
   ```powershell
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/short-bug-description
   ```

2. **Make your changes** following the coding standards below.

3. **Test** your changes thoroughly (see [Testing Requirements](#-testing-requirements)).

4. **Commit** with a clear message (see [Commit Conventions](#-commit--pr-conventions)).

5. **Push** your branch and open a Pull Request:
   ```powershell
   git push origin feature/your-feature-name
   ```

6. **Fill out the PR description** explaining *what* you changed and *why*.

---

## 📐 Coding Standards

### Python Style

| Rule | Details |
|------|---------|
| **Formatting** | Follow [PEP 8](https://peps.python.org/pep-0008/). Use 4 spaces for indentation. |
| **Max line length** | 120 characters. |
| **Type hints** | **Required** on all function signatures. |
| **Docstrings** | **Required** on every public function, following Google-style format (see below). |
| **Imports** | Group as: stdlib → third-party → local. No wildcard imports (`from x import *`). |
| **Logging** | Use `logging.getLogger(__name__)` — **never** `print()` for output. |
| **Async I/O** | All file I/O in tool functions must use `asyncio.to_thread()` for blocking operations. |
| **Stdout** | **Never** write to `stdout`. It is reserved for MCP JSON-RPC. Use `stderr` for logs. |

### Docstring Format

```python
def my_function(param: str, flag: bool = False) -> str:
    """Short one-line summary of what this function does.

    Longer description if necessary, explaining behavior,
    edge cases, or design rationale.

    Args:
        param: Description of the parameter.
        flag: Description of the flag (default: False).

    Returns:
        Description of the return value.
    """
```

### Return Format for Tools

All MCP tool functions must return **JSON strings** via `json.dumps()`:

```python
return json.dumps({"result": "success", "data": {...}})
```

For errors, return a JSON object with an `"error"` key — do **not** raise exceptions to the client:

```python
return json.dumps({"error": f"File not found: {path}"})
```

---

## 🧩 Adding New Tools

### Step 1 — Choose the Right Module

| Module | Purpose |
|--------|---------|
| `system_tools.py` | OS, hardware, processes, shell commands |
| `file_tools.py` | File/directory CRUD and search |
| `web_tools.py` | HTTP requests, web search, downloads |
| `app_tools.py` | Application install/uninstall/update (winget) |
| `utility_tools.py` | Clipboard, screenshots, opening apps/files |

> If your tool doesn't fit any existing module, **open an issue first** to discuss creating a new one.

### Step 2 — Follow the Registration Pattern

Every tool module uses a `register_tools(mcp)` function. Add your tool inside it:

```python
def register_tools(mcp):
    # ... existing tools ...

    @mcp.tool()
    async def your_new_tool(param: str, option: int = 10) -> str:
        """Clear description of what this tool does.

        Args:
            param: What this parameter represents.
            option: What this option controls (default: 10).
        """
        try:
            # Your implementation
            result = await asyncio.to_thread(blocking_operation, param)
            return json.dumps({"result": result})
        except Exception as e:
            logger.error("your_new_tool failed: %s", e)
            return json.dumps({"error": str(e)})
```

### Step 3 — Security Compliance

Every new tool **must** comply with these security rules:

| Scenario | Requirement |
|----------|-------------|
| Accepts a **file path** | Validate with `is_path_allowed()` from `security_config.py` |
| Accepts a **URL** | Validate with `is_url_safe()` from `security_config.py` |
| Opens/executes a **file or app** | Validate with `is_execution_safe()` from `security_config.py` |
| **Destructive** operation (delete, kill, uninstall, etc.) | Use `create_confirmation_token()` from `safety.py` |

Example — path validation:

```python
from src.security_config import is_path_allowed

allowed, reason = is_path_allowed(path)
if not allowed:
    return json.dumps({"error": reason})
```

Example — destructive operation:

```python
from src.safety import create_confirmation_token

return create_confirmation_token(
    action_type="delete_resource",
    description=f"Delete resource '{name}'",
    action_fn=_do_delete,
)
```

### Step 4 — Update Documentation

- Add your new tool to the relevant table in `README.md` under **Available Tools**.
- Mark destructive tools with ⚠️.

---

## 🛡️ Security Guidelines

> [!CAUTION]
> Security is **non-negotiable**. PRs that weaken or bypass security protections will be rejected.

### Rules

1. **Never bypass** the path, URL, or execution validation in `security_config.py`.
2. **Never remove** entries from `BLOCKED_DIRECTORIES`, `BLOCKED_WRITE_EXTENSIONS`, or `_BLOCKED_HOSTNAMES`.
3. **All destructive operations** must go through the two-phase confirmation system in `safety.py`.
4. **Do not allow** writing executable file types (`.exe`, `.bat`, `.ps1`, `.sh`, etc.).
5. **Do not allow** access to system directories (`C:\Windows`, `C:\Program Files`, `/etc`, etc.).
6. **Do not allow** SSRF — no requests to internal IPs, localhost, or cloud metadata endpoints.
7. **Never expose** sensitive data (API keys, tokens, passwords) in logs or tool responses.

### If You Add a New Security Rule

- Add it to `security_config.py`.
- Add corresponding tests to `test_security.py`.
- Update `SECURITY_REPORT.md` to document the new protection.

---

## ✅ Testing Requirements

### Before Submitting a PR

1. **Server starts without errors:**
   ```powershell
   python server.py
   ```

2. **Security tests pass (all must pass):**
   ```powershell
   python -m pytest test_security.py -v
   ```

3. **No new warnings or errors** in the output.

### When Adding Tests

- Place security-related tests in `test_security.py`.
- Use descriptive test names: `test_<what>_<expected_behavior>`.
- Cover both **allowed** and **blocked** scenarios.

---

## 💬 Commit & PR Conventions

### Branch Naming

```
feature/<short-description>      # New features
fix/<short-description>          # Bug fixes
security/<short-description>     # Security improvements
docs/<short-description>         # Documentation only
refactor/<short-description>     # Code refactoring (no behavior change)
```

### Commit Messages

Use the format: `type: short description`

```
feat: add disk usage monitoring tool
fix: handle empty directory in list_files
security: block access to registry files
docs: update README with new tool table
refactor: extract helper for path validation
test: add SSRF tests for IPv6 addresses
```

| Type | Use For |
|------|---------|
| `feat` | New features or tools |
| `fix` | Bug fixes |
| `security` | Security patches or hardening |
| `docs` | Documentation changes only |
| `refactor` | Restructuring without behavior change |
| `test` | Adding or updating tests |
| `chore` | Build, config, or dependency updates |

### Pull Request Checklist

Before requesting a review, confirm:

- [ ] My code follows the coding standards above.
- [ ] I've added type hints and docstrings to all new functions.
- [ ] I've validated inputs using `security_config.py` where applicable.
- [ ] Destructive operations use the confirmation token system.
- [ ] I've added/updated tests for my changes.
- [ ] All existing tests pass.
- [ ] I've updated `README.md` if I added or changed tools.
- [ ] I've tested the server starts successfully.
- [ ] My branch is up to date with `main`.

---

## 🎯 What We Accept

### ✅ Welcome

- New useful tools that follow the architecture.
- Security improvements and hardening.
- Bug fixes with clear reproduction steps.
- Documentation improvements.
- Performance optimizations.
- Cross-platform support improvements.

### ❌ Will Be Rejected

- Changes that bypass or weaken security protections.
- Tools that write to `stdout` (breaks MCP JSON-RPC).
- Code without type hints or docstrings.
- Large changes without a prior issue discussion.
- Breaking changes to the existing tool API without an issue.

---

## ❓ Need Help?

- **Found a bug?** [Open an issue](https://github.com/ViswaSrimaan/mcp_servers/issues/new) with steps to reproduce.
- **Have a feature idea?** Open an issue to discuss it before coding.
- **Questions?** Start a discussion on the repository.

---

Thank you for contributing! Every improvement — big or small — makes this project better for everyone. ⭐
