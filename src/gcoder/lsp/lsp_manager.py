import asyncio
import logging
import subprocess
import atexit
import socket
import platform
import os
from typing import Optional, Dict, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)
from .lsp_client import LspClient, LspHandshakeHandler

LANGUAGE_SERVER_COMMANDS = {
    "python": ["pyright-langserver", "--stdio"],
    "javascript": ["typescript-language-server", "--stdio"],
    "typescript": ["typescript-language-server", "--stdio"],
    "csharp": ["omnisharp", "--stdio"]
}

# In-memory store for running LSP processes and servers
_active_lsp_servers: Dict[str, Dict] = {}

def _find_free_port() -> int:
    """Finds an available TCP port on the local machine."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

async def _cleanup_lsp_servers():
    """Ensures all LSP servers and TCP bridges are shut down when the program exits."""
    for lang, server_info in list(_active_lsp_servers.items()):
        tcp_server = server_info.get("tcp_server")
        lsp_process = server_info.get("lsp_process")
        
        if tcp_server:
            tcp_server.close()
            await tcp_server.wait_closed()
            logger.info(f"Closed TCP bridge for {lang}.")
        
        if lsp_process and lsp_process.returncode is None:
            logger.info(f"Terminating LSP process for {lang} (PID: {lsp_process.pid}).")
            lsp_process.terminate()
            try:
                await lsp_process.wait()
            except Exception:
                lsp_process.kill()
        
        _active_lsp_servers.pop(lang, None)

# Use atexit to ensure cleanup happens, but an async-compatible one is better if the
# main application loop supports it. For a CLI, this is a reasonable fallback.
def _sync_cleanup():
    try:
        asyncio.run(_cleanup_lsp_servers())
    except RuntimeError:
        # This can happen if the event loop is already closed.
        pass

atexit.register(_sync_cleanup)


class LspManager:
    """
    Manages the lifecycle of Language Server Protocol servers using a native Python
    asyncio TCP bridge, making it fully cross-platform.
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
        Starts the LSP server and a native Python asyncio TCP bridge.
        """
        if language not in LANGUAGE_SERVER_COMMANDS:
            logger.error(f"No LSP server command configured for language '{language}'.")
            return None
        
        lsp_command = LANGUAGE_SERVER_COMMANDS[language]
        port = _find_free_port()

        try:
            # 1. Start the actual LSP server process
            lsp_process = await asyncio.create_subprocess_exec(
                *lsp_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            logger.info(f"Started {language} LSP process with PID: {lsp_process.pid}")

            # 2. Define the two-way bridge logic
            async def bridge(tcp_reader: asyncio.StreamReader, tcp_writer: asyncio.StreamWriter):
                client_host, client_port = tcp_writer.get_extra_info('peername')
                logger.info(f"LSP client connected to {language} bridge from {client_host}:{client_port}")

                async def client_to_lsp():
                    while not tcp_reader.at_eof():
                        data = await tcp_reader.read(4096)
                        if not data: break
                        lsp_process.stdin.write(data)
                        await lsp_process.stdin.drain()

                async def lsp_to_client():
                    while not lsp_process.stdout.at_eof():
                        data = await lsp_process.stdout.read(4096)
                        if not data: break
                        tcp_writer.write(data)
                        await tcp_writer.drain()
                
                async def log_stderr():
                    while not lsp_process.stderr.at_eof():
                        line = await lsp_process.stderr.readline()
                        if line:
                            logger.debug(f"LSP stderr ({language}): {line.decode().strip()}")

                # Run all three tasks concurrently. If any one of them finishes
                # (due to a closed connection), the others will be cancelled.
                try:
                    await asyncio.gather(
                        client_to_lsp(),
                        lsp_to_client(),
                        log_stderr()
                    )
                finally:
                    tcp_writer.close()
                    await tcp_writer.wait_closed()
                    logger.info(f"LSP client disconnected from {language} bridge.")

            # 3. Start the TCP server that will use our bridge logic
            tcp_server = await asyncio.start_server(bridge, '127.0.0.1', port)
            logger.info(f"Started native Python TCP bridge for {language} on port {port}.")
            
            server_info = {
                "lsp_process": lsp_process,
                "tcp_server": tcp_server,
                "port": port
            }
            _active_lsp_servers[language] = server_info
            
            return server_info

        except FileNotFoundError:
            logger.error(f"The LSP command '{lsp_command[0]}' was not found. Please install it to use code intelligence tools.")
            return None
        except Exception as e:
            logger.error(f"Failed to start native LSP bridge for {language}: {e}", exc_info=True)
            return None

    async def get_client(self, file_path: str) -> Optional[LspHandshakeHandler]:
        """
        Gets a ready-to-use LSP client for a given file.
        It will start the appropriate language server and bridge if they are not already running.
        """
        language = self._get_language_for_file(file_path)
        if not language:
            logger.warning(f"No language detected for file: {file_path}")
            return None

        server_info = _active_lsp_servers.get(language)
        # Check if the underlying LSP process is still running
        if server_info is None or server_info["lsp_process"].returncode is not None:
            logger.info(f"LSP server for {language} not running. Starting a new one.")
            server_info = await self._start_server_process(language)
        
        if not server_info:
            return None

        port = server_info["port"]
        client = LspClient(host="127.0.0.1", port=port)
        
        return LspHandshakeHandler(client, self.workspace_root)