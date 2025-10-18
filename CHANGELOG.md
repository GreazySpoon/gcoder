# Changelog for G-Coder

All notable changes in this project will be documented in this file.

This version (0.2.0) focuses on core stability, developer experience (DX), and introducing a Human-in-the-Loop (HITL) approval gate for sensitive operations.

## [0.2.0] - YYYY-MM-DD (Current)

### ✨ Features & Improvements
- Implemented a Human-in-the-Loop (HITL) approval mechanism via `rich` prompts for sensitive commands (`write_file`, `edit_file`, `run_in_terminal`, etc.).
- Introduced rich, informative panels to the terminal output to clearly display the *plan* (arguments) before a tool executes.
- Enhanced CLI startup: Added display of the G-Coder version number and cleaned up the initial banner output.
- Improved command separation in the interactive session by adding a clear separator line between user input and agent response.

### 🐛 Bug Fixes & Refactoring
- **`callbacks.py`:** Major refactoring to standardize tool output presentation, including consistent panel titles for different tool results and better error messaging.
- **`terminal.py`:** Standardized terminal interface styling and suppressed system errors (`stderr`) from tool execution logs to keep the main output clean.
- **`README.md`:** Updated ASCII branding and replaced the simple MIT license text with a more comprehensive, if slightly redundant, license block.
