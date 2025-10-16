
import asyncio
import logging
import subprocess
import atexit
import socket
import platform
import os
from typing import Optional, Dict
from pathlib import Path

logger = logging.getLogger(__name__)
from .lsp_client import LspClient, LspHandshakeHandler
LANGUAGE_SERVER_COMMANDS = {
    "python": "pyright-langserver --stdio",
    "javascript": "typescript-language-server --stdio",
    "typescript": "typescript-language-server --stdio",
    "csharp": "omnisharp --stdio"
}

# In-memory store for running LSP processes to avoid restarting them constantly
_active_lsp_servers: Dict[str, Dict] = {}

def _find_free_port() -> int:
    """Finds an available TCP port on the local machine."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def _cleanup_lsp_servers():
    """Ensures all LSP server and socat processes are terminated when the program exits."""
    for lang, server_info in _active_lsp_servers.items():
        process = server_info.get("process")
        if process:
            logger.info(f"Terminating socat/LSP process for {lang} (PID: {process.pid}).")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

atexit.register(_cleanup_lsp_servers)

class LspManager:
    """
    Manages the lifecycle of local Language Server Protocol servers using the robust
    socat TCP bridge architecture.
    """
    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root

    def _get_language_for_file(self, file_path: str) -> Optional[str]:
        """Determines the language based on the file extension."""
        if file_path.endswith(('.py', '.pyw')):
            return 'python'
        if file_path.endswith(('.js', '.jsx', '.ts', '.tsx')):
            return 'typescript'
        if file_path.endswith(('.cs')):
            return 'csharp'
        return None

    async def _start_server_process(self, language: str) -> Optional[Dict]:
        """
        Starts the LSP server and its socat TCP bridge as a detached background process.
        """
        if platform.system() == "Windows":
            logger.error("LSP tools are not supported on Windows in this version due to 'socat' dependency.")
            return None

        if language not in LANGUAGE_SERVER_COMMANDS:
            logger.error(f"No LSP server command configured for language '{language}'.")
            return None
        
        lsp_command = LANGUAGE_SERVER_COMMANDS[language]
        port = _find_free_port()
        
        # This command creates a TCP listener on a free port and forwards all traffic
        # to the standard I/O of the actual LSP server process.
        socat_command = f'socat TCP-LISTEN:{port},fork,reuseaddr EXEC:"{lsp_command}"'
        
        # --- MODIFICATION FOR DEBUGGING ---
        # --- MODIFICATION FOR DEBUGGING ---
        # Log stderr to a file in the user's home directory for cross-platform consistency.
        HOME = Path.home()
        if platform.system() == "Windows":
            # Use AppData/Roaming/Gcoder for Windows
            config_dir = HOME / "AppData" / "Roaming" / "Gcoder"
        elif platform.system() == "Darwin":
            # Use Library/Application Support/Gcoder for macOS
            config_dir = HOME / "Library" / "Application Support" / "Gcoder"
        else:
            # Use .config/gcoder for Linux (XDG Base Directory Specification)
            config_dir = HOME / ".config" / "gcoder"

        config_dir.mkdir(parents=True, exist_ok=True)
        error_log_path = str(config_dir / "lsp_stderr.log")
        error_log_file = open(error_log_path, "a")        
        try:
            # We run this as a detached background process.
            process = subprocess.Popen(
                socat_command,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=error_log_file, # Capture stderr instead of discarding it
                preexec_fn=os.setsid # Detach from the current terminal session
            )
            
            # Give the process a moment to start up and begin listening
            await asyncio.sleep(1.5)

            server_info = {"process": process, "port": port, "log_file": error_log_file}
            _active_lsp_servers[language] = server_info

            logger.info(f"Started {language} LSP bridge on port {port} with PID: {process.pid}")
            return server_info
        except FileNotFoundError:
            logger.error(f"The 'socat' command was not found. Please install socat to use code intelligence tools.")
            error_log_file.close()
            return None
        except Exception as e:
            logger.error(f"Failed to start LSP socat bridge for {language}: {e}", exc_info=True)
            error_log_file.close()
            return None

    async def get_client(self, file_path: str) -> Optional[LspHandshakeHandler]:
        """
        Gets a ready-to-use LSP client for a given file.
        It will start the appropriate language server if it's not already running.
        """
        language = self._get_language_for_file(file_path)
        if not language:
            logger.warning(f"No language detected for file: {file_path}")
            return None

        server_info = _active_lsp_servers.get(language)
        # Check if process exists and is still running
        if server_info is None or server_info["process"].poll() is not None:
            logger.info(f"LSP server for {language} not running. Starting a new one.")
            server_info = await self._start_server_process(language)
        
        if not server_info:
            return None

        port = server_info["port"]
        client = LspClient(host="127.0.0.1", port=port)
        
        return LspHandshakeHandler(client, self.workspace_root)

