# test_lsp.py

import asyncio
import logging
import subprocess
import os
import json
from pathlib import Path
from typing import Optional, Dict, Any

# --- Configure detailed logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s'
)
logger = logging.getLogger(__name__)


class LspTestClient:
    """A self-contained LSP client for this test script."""
    def __init__(self, process: asyncio.subprocess.Process):
        self._process = process
        self._reader = process.stdout
        self._writer = process.stdin
        self._request_id = 1
        self._reader_task: Optional[asyncio.Task] = None
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    def start_reader_task(self):
        self._reader_task = asyncio.create_task(self._read_loop())

    def is_running(self) -> bool:
        return self._process.returncode is None

    async def _read_loop(self):
        try:
            while self.is_running() and self._reader and not self._reader.at_eof():
                header_bytes = await self._reader.readuntil(b'\r\n\r\n')
                header_str = header_bytes.decode('utf-8')
                content_length_str = [line for line in header_str.split('\r\n') if line.lower().startswith('content-length')]
                if not content_length_str: continue
                content_length = int(content_length_str[0].split(':')[1].strip())
                content_bytes = await self._reader.readexactly(content_length)
                response = json.loads(content_bytes.decode('utf-8'))
                
                request_id = response.get("id")
                if request_id is not None:
                    async with self._lock:
                        future = self._pending_requests.pop(request_id, None)
                    if future and not future.done():
                        logger.info(f"Dispatching response for request ID: {request_id}")
                        future.set_result(response)
                else:
                    logger.info(f"Received server notification: {response.get('method')}")
                    # Log the actual message content for debugging
                    if 'params' in response and 'message' in response['params']:
                        logger.info(f"Server message: {response['params']['message']}")
        except asyncio.IncompleteReadError:
            logger.warning("LSP server closed stdout. Connection lost.")
        except asyncio.CancelledError: 
            logger.info("Reader loop cancelled")
        except Exception as e:
            logger.error(f"Error in reader loop: {e}", exc_info=True)

    def _encode_message(self, message: Dict[str, Any]) -> bytes:
        content = json.dumps(message, separators=(',', ':'))  # Compact JSON
        content_bytes = content.encode('utf-8')
        header = f"Content-Length: {len(content_bytes)}\r\n\r\n"
        return header.encode('utf-8') + content_bytes

    async def send_request(self, method: str, params: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
        if not self.is_running() or self._writer.is_closing(): 
            raise ConnectionError("Writer is closed.")
        
        future = asyncio.get_running_loop().create_future()
        async with self._lock:
            request_id = self._request_id
            self._pending_requests[request_id] = future
            self._request_id += 1
        
        message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        encoded_message = self._encode_message(message)
        self._writer.write(encoded_message)
        await self._writer.drain()
        logger.info(f"Sent request ID {request_id}: {method}")
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for response to request ID {request_id}: {method}")
            raise

    async def send_notification(self, method: str, params: Dict[str, Any]):
        if not self.is_running() or self._writer.is_closing(): 
            raise ConnectionError("Writer is closed.")
        
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        encoded_message = self._encode_message(message)
        self._writer.write(encoded_message)
        await self._writer.drain()
        logger.info(f"Sent notification: {method}")

    async def shutdown(self):
        if self.is_running():
            try:
                await self.send_notification("shutdown", {})
                await self.send_notification("exit", {})
            except ConnectionError: 
                pass
            except Exception as e:
                logger.warning(f"Error during shutdown: {e}")
            finally:
                if self._process.returncode is None:
                    try:
                        self._process.terminate()
                        try:
                            await asyncio.wait_for(self._process.wait(), timeout=5.0)
                        except asyncio.TimeoutError:
                            logger.warning("Process did not terminate gracefully, killing...")
                            self._process.kill()
                            await self._process.wait()
                    except ProcessLookupError:
                        pass  # Process already terminated
                if self._reader_task: 
                    self._reader_task.cancel()
                    try:
                        await self._reader_task
                    except asyncio.CancelledError:
                        pass
                logger.info("LSP server process terminated.")


async def main():
    PROJECT_ROOT = os.getcwd()
    LSP_EXECUTABLE = "/usr/local/bin/pyright-langserver"
    SYMBOL_TO_FIND = "LspClient"
    
    init_file_path = Path(PROJECT_ROOT) / "src" / "gcoder" / "lsp" / "lsp_client.py"
    if not init_file_path.exists():
        logger.error(f"CRITICAL: Target file does not exist: {init_file_path}")
        return

    logger.info(f"Project Root: {PROJECT_ROOT}")
    logger.info(f"LSP Executable: {LSP_EXECUTABLE}")
    
    # First, let's verify the symbol actually exists in the file
    file_content = init_file_path.read_text()
    if SYMBOL_TO_FIND in file_content:
        logger.info(f"✅ Symbol '{SYMBOL_TO_FIND}' found in {init_file_path.name}")
    else:
        logger.error(f"❌ Symbol '{SYMBOL_TO_FIND}' NOT found in {init_file_path.name}")
        # Let's look for class definitions in the file
        lines = file_content.split('\n')
        classes = [line.strip() for line in lines if line.strip().startswith('class ')]
        logger.info(f"Classes found in file: {classes}")
        return

    # Launch the LSP server
    process = await asyncio.create_subprocess_exec(
        LSP_EXECUTABLE,
        "--stdio",
        cwd=PROJECT_ROOT,
        stdout=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    client = LspTestClient(process)
    client.start_reader_task()

    try:
        # Initialize with workspace folder support
        initialize_params = {
            "processId": os.getpid(),
            "rootUri": f"file://{PROJECT_ROOT}",
            "rootPath": PROJECT_ROOT,
            "capabilities": {
                "workspace": {
                    "symbol": {
                        "dynamicRegistration": True,
                        "symbolKind": {
                            "valueSet": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26]
                        }
                    },
                    "workspaceFolders": {
                        "supported": True,
                        "changeNotifications": True
                    }
                },
                "textDocument": {
                    "synchronization": {
                        "didOpen": True,
                        "didClose": True,
                        "didChange": True
                    }
                }
            },
            "initializationOptions": {
                "hostName": "Test Client",
                "telemetryLevel": "off"
            },
            "workspaceFolders": [
                {
                    "uri": f"file://{PROJECT_ROOT}",
                    "name": "gcoder-project"
                }
            ]
        }
        
        logger.info("Sending initialize request...")
        response = await client.send_request("initialize", initialize_params, timeout=10.0)
        logger.info(f"Initialize response received")
        
        await client.send_notification("initialized", {})
        logger.info("LSP handshake complete.")
        
        # Wait a bit more for initialization to complete
        await asyncio.sleep(2)
        
        # If the server supports workspace folders, send a workspace folder change notification
        if response.get('result', {}).get('capabilities', {}).get('workspace', {}).get('workspaceFolders', {}).get('supported'):
            await client.send_notification("workspace/didChangeWorkspaceFolders", {
                "event": {
                    "added": [
                        {
                            "uri": f"file://{PROJECT_ROOT}",
                            "name": "gcoder-project"
                        }
                    ],
                    "removed": []
                }
            })
            logger.info("Sent workspace folder change notification")
            await asyncio.sleep(2)  # Wait for workspace folder to be processed

        # Open the file
        file_content = init_file_path.read_text()
        await client.send_notification("textDocument/didOpen", {
            "textDocument": { 
                "uri": init_file_path.as_uri(), 
                "languageId": "python", 
                "version": 1, 
                "text": file_content 
            }
        })
        logger.info(f"Sent 'didOpen' for {init_file_path.name}. Giving server more time to index...")
        
        # Wait for indexing to complete
        for i in range(15):  # Wait up to 15 seconds
            await asyncio.sleep(1)
            logger.info(f"Indexing... {i+1}/15 seconds")
        
        # Try workspace symbol first
        logger.info("--- Starting Workspace Symbol Search ---")
        response = await client.send_request("workspace/symbol", {"query": SYMBOL_TO_FIND})
        all_symbols = response.get('result', [])
        found_symbol = [s for s in all_symbols if s.get("name") == SYMBOL_TO_FIND]

        print("\n" + "="*50)
        if found_symbol:
            print(f"✅ FINAL RESULT: Symbol '{SYMBOL_TO_FIND}' FOUND via workspace/symbol!")
            print(json.dumps(found_symbol, indent=2))
        else:
            print(f"❌ Symbol '{SYMBOL_TO_FIND}' NOT FOUND via workspace/symbol.")
            print(f"Found {len(all_symbols)} symbols via workspace/symbol, showing first 10:")
            for symbol in all_symbols[:10]:
                name = symbol.get('name', 'N/A')
                kind = symbol.get('kind', 'N/A')
                location_uri = symbol.get('location', {}).get('uri', 'N/A') if 'location' in symbol else 'N/A'
                print(f"  - {name} (kind: {kind}) - {location_uri}")
            
            # Try document symbol with a longer timeout
            logger.info("--- Trying Document Symbol Search ---")
            try:
                doc_response = await client.send_request("textDocument/documentSymbol", {
                    "textDocument": {"uri": init_file_path.as_uri()}
                }, timeout=15.0)  # Increased timeout
                
                doc_symbols = doc_response.get('result', [])
                doc_found_symbol = []
                
                # Recursively search through document symbols (they can be nested)
                def find_symbol_recursive(symbols, target_name):
                    found = []
                    for sym in symbols:
                        if sym.get('name') == target_name:
                            found.append(sym)
                        # Check children if they exist
                        if 'children' in sym and sym['children']:
                            found.extend(find_symbol_recursive(sym['children'], target_name))
                    return found
                
                doc_found_symbol = find_symbol_recursive(doc_symbols, SYMBOL_TO_FIND)
                
                if doc_found_symbol:
                    print(f"✅ Symbol '{SYMBOL_TO_FIND}' FOUND via documentSymbol!")
                    print(json.dumps(doc_found_symbol, indent=2))
                else:
                    print(f"❌ Symbol '{SYMBOL_TO_FIND}' NOT FOUND via documentSymbol either.")
                    print(f"Found {len(doc_symbols)} symbols in document, showing first 10:")
                    for symbol in doc_symbols[:10]:
                        name = symbol.get('name', 'N/A')
                        kind = symbol.get('kind', 'N/A')
                        detail = symbol.get('detail', 'N/A')
                        print(f"  - {name} (kind: {kind}) - {detail}")
            except Exception as e:
                print(f"Document symbol request failed: {e}")

        print("="*50 + "\n")

    except asyncio.TimeoutError as e:
        logger.error(f"Timeout error: {e}")
        try:
            stderr_output = await asyncio.wait_for(process.stderr.read(), timeout=2.0)
            if stderr_output:
                logger.error(f"Server stderr: {stderr_output.decode()}")
        except asyncio.TimeoutError:
            logger.error("Could not read stderr - timeout")
    except Exception as e:
        logger.error(f"An error occurred during the test: {e}", exc_info=True)
        try:
            stderr_output = await asyncio.wait_for(process.stderr.read(), timeout=2.0)
            if stderr_output:
                logger.error(f"Server stderr: {stderr_output.decode()}")
        except asyncio.TimeoutError:
            logger.error("Could not read stderr")
    finally:
        logger.info("Cleaning up...")
        await client.shutdown()
        logger.info("Test finished.")

if __name__ == "__main__":
    asyncio.run(main())