# src/gcoder/lsp/lsp_client.py

import json
import logging
import asyncio
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

class LspClient:
    """
    A robust client for communicating with a Language Server Protocol server.
    This version uses a background reader task and futures to correctly handle
    concurrent requests and unsolicited server notifications without disconnecting.
    """
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._request_id = 1
        self._reader_task: Optional[asyncio.Task] = None
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    def is_connected(self) -> bool:
        """Checks if the writer object exists and is not closing."""
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self):
        """Establishes a connection to the LSP server and starts the reader task."""
        if self.is_connected(): return
        try:
            self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
            self._reader_task = asyncio.create_task(self._read_loop())
            logger.info(f"LSP Client: Connected to {self.host}:{self.port}")
        except ConnectionRefusedError as e:
            logger.error(f"LSP Client: Connection refused at {self.host}:{self.port}. Is the server running?")
            raise ConnectionError("LSP server is not running or refused the connection.") from e
        except Exception as e:
            logger.error(f"LSP Client: Failed to connect: {e}", exc_info=True)
            raise ConnectionError(f"Failed to connect to LSP server: {e}") from e

    async def disconnect(self):
        """Shuts down the connection and cancels all pending requests."""
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass  # This is expected.
        self._reader_task = None
        
        if self._writer:
            if self._writer.can_write_eof():
                self._writer.write_eof()
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError):
                pass  # The other end may have already closed.
            logger.info(f"LSP Client: Disconnected from {self.host}:{self.port}")

        self._reader, self._writer = None, None
        
        async with self._lock:
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(ConnectionError("LSP Client disconnected."))
            self._pending_requests.clear()

    async def _read_loop(self):
        """A background task that continuously reads and dispatches messages from the server."""
        try:
            while self.is_connected() and self._reader and not self._reader.at_eof():
                response = await self._read_message_internal()
                if response is None:
                    break  # Connection closed cleanly

                request_id = response.get("id")
                if request_id is not None:
                    async with self._lock:
                        future = self._pending_requests.pop(request_id, None)
                    if future and not future.done():
                        future.set_result(response)
                    else:
                        logger.warning(f"LSP received response for unknown or already handled request ID: {request_id}")
                else:
                    # This is an unsolicited notification from the server.
                    # It's crucial to handle these without breaking the flow.
                    method = response.get('method', 'unknown_notification')
                    logger.debug(f"LSP received notification: {method}")
        except asyncio.CancelledError:
            logger.info("LSP reader task was cancelled.")
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            logger.warning("LSP server closed the connection unexpectedly.")
        except Exception as e:
            logger.error(f"LSP reader task failed with an unexpected error: {e}", exc_info=True)
        finally:
            if self.is_connected():
                asyncio.create_task(self.disconnect())

    def _encode_message(self, message: Dict[str, Any]) -> bytes:
        """Encodes a message dictionary into the LSP byte format."""
        content = json.dumps(message)
        content_bytes = content.encode('utf-8')
        header = f"Content-Length: {len(content_bytes)}\r\n\r\n"
        return header.encode('utf-8') + content_bytes

    async def _read_message_internal(self) -> Optional[Dict[str, Any]]:
        """Internal message reader, only called by _read_loop."""
        if not self._reader: return None
        # The header must end with b'\r\n\r\n'
        separator = b'\r\n\r\n'
        header_bytes = await self._reader.readuntil(separator)
        
        header_str = header_bytes.decode('utf-8')
        content_length_str = [line for line in header_str.split('\r\n') if line.lower().startswith('content-length')]
        if not content_length_str:
            logger.warning(f"LSP received an invalid header: {header_str}")
            return None
        
        content_length = int(content_length_str[0].split(':')[1].strip())
        content_bytes = await self._reader.readexactly(content_length)
        return json.loads(content_bytes.decode('utf-8'))

    async def send_request(self, method: str, params: Dict[str, Any], timeout: float = 15.0) -> Dict[str, Any]:
        """Sends a request and waits for a corresponding response."""
        if not self.is_connected() or self._writer is None:
            raise ConnectionError("Cannot send request, not connected.")
        
        future = asyncio.get_running_loop().create_future()
        async with self._lock:
            request_id = self._request_id
            self._pending_requests[request_id] = future
            self._request_id += 1

        message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        self._writer.write(self._encode_message(message))
        await self._writer.drain()
        
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as e:
            # Clean up the pending request on timeout
            async with self._lock:
                self._pending_requests.pop(request_id, None)
            raise TimeoutError(f"LSP request '{method}' timed out after {timeout}s.") from e

    async def send_notification(self, method: str, params: Dict[str, Any]):
        """Sends a notification without expecting a response."""
        if not self.is_connected() or self._writer is None:
            raise ConnectionError("Cannot send notification, not connected.")
        
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        self._writer.write(self._encode_message(message))
        await self._writer.drain()


class LspHandshakeHandler:
    """Handles the LSP connection, handshake, and shutdown sequence."""
    def __init__(self, client: LspClient, workspace_path: str):
        self.client = client
        self.workspace_uri = f"file://{workspace_path}"

    async def __aenter__(self):
        """Connects and performs the LSP initialization handshake."""
        await self.client.connect()
        initialize_params = {
            "processId": os.getpid(),
            "rootUri": self.workspace_uri,
            "rootPath": self.workspace_uri.replace('file://', ''),
            "capabilities": {
                "workspace": {
                    "symbol": {},
                    "workspaceFolders": {
                        "supported": True,
                        "changeNotifications": True
                    }
                },
                "textDocument": {
                    "documentSymbol": { "hierarchicalDocumentSymbolSupport": True },
                    "references": {},
                    "diagnostic": {},
                    "synchronization": {
                        "didOpen": True,
                        "didClose": True,
                        "didChange": True
                    }
                }
            },
            "workspaceFolders": [
                {
                    "uri": self.workspace_uri,
                    "name": os.path.basename(self.workspace_uri.replace('file://', ''))
                }
            ],
            "trace": "off"
        }
        
        init_response = await self.client.send_request("initialize", initialize_params)
        if not init_response or 'result' not in init_response:
            await self.client.disconnect()
            raise ConnectionError("LSP server did not respond correctly to 'initialize' request.")
            
        await self.client.send_notification("initialized", {})
        
        # Send workspace folder notification to trigger indexing
        await self.client.send_notification("workspace/didChangeWorkspaceFolders", {
            "event": {
                "added": [
                    {
                        "uri": self.workspace_uri,
                        "name": os.path.basename(self.workspace_uri.replace('file://', ''))
                    }
                ],
                "removed": []
            }
        })
        
        # Wait a bit for workspace to be processed
        await asyncio.sleep(2)
        
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Performs a graceful shutdown of the LSP connection."""
        if self.client.is_connected():
            try:
                # We don't wait for shutdown response as the server might close immediately
                await self.client.send_request("shutdown", {}, timeout=2.0)
            except (ConnectionError, TimeoutError):
                 logger.warning("LSP Graceful Shutdown: Connection issue or timeout during shutdown.")
            except Exception as e:
                logger.warning(f"LSP Graceful Shutdown: Error during shutdown request: {e}")
        
        if self.client.is_connected():
            try:
                # Exit is a notification, we don't expect a response.
                await self.client.send_notification("exit", {})
            except ConnectionError:
                pass # It's fine if it's already closed.
        
        await self.client.disconnect()

    async def execute_request(self, method: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Executes a single LSP request within the managed session."""
        try:
            return await self.client.send_request(method, params)
        except Exception as e:
            logger.error(f"LSP request failed for method '{method}': {e}", exc_info=True)
            return {"error": {"code": -32000, "message": f"LSP request execution failed: {e}"}}

    async def notify_did_open(self, file_path: str, file_content: str):
        """Sends a 'textDocument/didOpen' notification."""
        params = {"textDocument": {"uri": f"file://{file_path}", "languageId": "python", "version": 1, "text": file_content}}
        await self.client.send_notification("textDocument/didOpen", params)

