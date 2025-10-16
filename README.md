# GCoder Project: Autonomous AI Agent Framework

This repository hosts an advanced, modular AI agent framework designed for complex system interaction, development assistance, and automated task execution. The core operational paradigm strictly adheres to the **Observe -> Orient -> Decide -> Act -> Verify** lifecycle.

![General Agent Interface](screenshots/screen1.png)

---
**Note:** The screenshot above illustrates the typical interactive environment or interface of the running agent.
---

## 1. Project Architecture Overview

The framework is organized into functional layers for clarity and extensibility:

| Path | Description | Key Files |
| :--- | :--- | :--- |
| **`src/gcoder/`** | Core Python logic and agent definition. | `main.py` (Entry Point) |
| **`src/gcoder/agents/`** | Implementations of the AI decision-makers. | `basic_agent.py`, `autonomous_agent.py` |
| **`src/gcoder/tools/`** | The comprehensive toolkit providing capabilities to the agents. | `execution_tools.py`, `file_tools.py`, `code_tools.py`, `vision_tools.py` |
| **`src/gcoder/prompts/`** | Stores system instructions and persona definitions. | `basic_agent_instruction.txt` |
| **`src/gcoder/lsp/`** | Integration layer for Language Server Protocol diagnostics. | `lsp_manager.py` |
| **`screenshots/`** | Visual documentation references. | `screen1.png`, `screen2.png` |

## 2. Setup and Installation

### Prerequisites

*   Python 3.8+
*   Node.js (Likely required due to `package.json` presence)

### Installation

1.  **Clone & Navigate:**
    ```bash
    git clone <repository-url>
    cd gcoder-project
    ```

2.  **Install Dependencies:**
    The presence of `pyproject.toml` suggests a modern dependency manager like Poetry or PDM.
    ```bash
    # Recommended (if using Poetry)
    poetry install
    
    # Fallback if necessary
    # pip install -r requirements.txt (if requirements.txt exists)
    
    # Install Node dependencies
    npm install
    ```

## 3. Execution and Operation

The application is executed via the main script, which handles argument parsing and initiates the primary agent loop.

**Running a Task (from `src/gcoder/main.py`):**
```bash
python src/gcoder/main.py --task "Analyze the code and update the README"
```

### Tool Capabilities Summary

Agents operate by leveraging the following tool categories:
*   **Execution:** `run_in_terminal` allows safe execution of shell commands (e.g., `ls`, `git`).
*   **File System:** Tools for reading, writing, and surgical editing of files (`read_file`, `edit_file`).
*   **Code Intelligence:** LSP-backed tools for finding definitions and references across the codebase.

## 4. Usage Example: File Modification Workflow

The agent excels at multi-step technical tasks. This secondary screenshot demonstrates a sequence where the agent reads file content and executes an edit based on a user request.

![Example Usage Workflow](screenshots/screen2.png)

## 5. Known Observations (From Code Inspection)

*   **Agent Configuration:** Agents like `basic_agent.py` have compile-time configuration toggles for enabling advanced features like **Thinking** and **Vision**.
*   **External Dependencies:** The `basic_agent.py` shows import errors related to `google.adk.models`, suggesting potential integration with an internal or specific Google SDK that might be missing or misconfigured in the current environment.

## 6. Configuration Files

Initial environment variables and settings should be checked in:
*   `example-config.ini`
*   `pyproject.toml` (for Python dependencies and metadata)