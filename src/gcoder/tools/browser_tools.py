from __future__ import annotations

import os
import re
import asyncio
import logging
import base64
import sys
import pathlib
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright, Error

# ADK and GenAI type imports
from google.genai import types
from google.adk.tools import BaseTool

if TYPE_CHECKING:
    from google.adk.models.llm_request import LlmRequest
    from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)

# --- The Main Browser Tool ---

class AIBrowserTool(BaseTool):
    """
    A stateful tool for an AI agent to interact with a web browser.
    It manages a persistent browser instance and provides actions for navigation
    and interaction, returning visual feedback after each action.
    """

    def __init__(self):
        super().__init__(
            name='browser_action',
            description="Performs an action in a web browser (e.g., GOTO, CLICK, TYPE). Returns the new visual state of the page."
        )
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.pages: Dict[int, Page] = {}
        self.next_page_id = 0
        self.active_page_id: Optional[int] = None

        # To hold screenshot data between run_async and process_llm_request
        self.last_raw_screenshot_bytes: Optional[bytes] = None
        self.last_labeled_screenshot_bytes: Optional[bytes] = None

        # Lock to prevent race conditions during initial browser setup
        self._setup_lock = asyncio.Lock()

    def _get_declaration(self) -> types.FunctionDeclaration | None:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    'action': types.Schema(
                        type=types.Type.STRING,
                        description="The action to perform.",
                        enum=['GOTO', 'CLICK', 'TYPE', 'SCROLL', 'GET_STATE', 'LIST_TABS', 'CLOSE_TAB']
                    ),
                    'url': types.Schema(type=types.Type.STRING, description="The URL or local file path (e.g., './index.html') to navigate to for the GOTO action."),
                    'element_id': types.Schema(type=types.Type.INTEGER, description="The ID of the interactive element for CLICK or TYPE actions."),
                    'text_to_type': types.Schema(type=types.Type.STRING, description="The text to enter for the TYPE action."),
                    'scroll_direction': types.Schema(type=types.Type.STRING, description="Direction to scroll: 'up' or 'down'."),
                    'force_click': types.Schema(type=types.Type.BOOLEAN, description="For the CLICK action, force the click even if the element is obscured by another element (e.g., a cookie banner)."),
                    'tab_id': types.Schema(type=types.Type.INTEGER, description="The target tab ID for the action. If not specified, the active tab is used."),
                    'save_screenshot_path': types.Schema(type=types.Type.STRING, description="Local path to save the raw screenshot to (optional).")
                },
                required=['action']
            ),
        )

    async def _install_playwright_deps(self) -> bool:
        """Runs playwright install --with-deps chromium."""
        logger.info("Chromium not found or check failed. Attempting to install...")
        try:
            print("Installing Playwright browser dependencies. This may require sudo and take a few minutes...")
            process_deps = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "playwright", "install-deps",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr_deps = await process_deps.communicate()
            if process_deps.returncode != 0:
                logger.warning(f"Playwright install-deps may have failed:\n{stderr_deps.decode()}")
            else:
                 print("Dependencies installed successfully.")

            process_chromium = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "playwright", "install", "chromium",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr_chromium = await process_chromium.communicate()

            if process_chromium.returncode == 0:
                logger.info("Playwright Chromium installed successfully.")
                print("Playwright Chromium installed successfully.")
                return True
            else:
                logger.error(f"Playwright install chromium failed:\n{stderr_chromium.decode()}")
                return False
        except Exception as e:
            logger.error(f"An error occurred during Playwright installation: {e}")
            return False

    async def _ensure_browser_is_ready(self):
        """Initializes the playwright and browser instance if not already present."""
        async with self._setup_lock:
            if self.browser and self.browser.is_connected():
                return
            logger.info("Initializing browser...")
            try:
                self.playwright = await async_playwright().start()
                await self.playwright.chromium.launch(headless=True)
            except Error:
                install_success = await self._install_playwright_deps()
                if not install_success:
                    raise RuntimeError("Failed to install Playwright Chromium. The tool cannot proceed.")

            is_headed = bool(os.environ.get('DISPLAY'))
            logger.info(f"Launching in {'headed' if is_headed else 'headless'} mode.")
            self.browser = await self.playwright.chromium.launch(headless=not is_headed)
            self.context = await self.browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'
            )
            await self._create_new_page()

    async def _create_new_page(self) -> Page:
        """Creates a new page, adds it to the pool, and makes it active."""
        if not self.context:
            raise RuntimeError("Browser context not available.")
        page = await self.context.new_page()
        page_id = self.next_page_id
        self.pages[page_id] = page
        self.active_page_id = page_id
        self.next_page_id += 1
        logger.info(f"Created and activated new tab with ID: {page_id}")
        return page

    async def _update_state_and_screenshots(self, page: Page, save_path: Optional[str] = None) -> Dict[str, Any]:
        """Generates raw and labeled screenshots and stores them as bytes."""
        try:
            self.last_raw_screenshot_bytes = await page.screenshot()
        except Error as e:
            return {"status": "error", "message": f"Failed to take screenshot: {e}"}

        if save_path:
            try:
                with open(save_path, "wb") as f: f.write(self.last_raw_screenshot_bytes)
                logger.info(f"Raw screenshot saved to {save_path}")
            except Exception as e:
                 logger.error(f"Failed to save screenshot to {save_path}: {e}")

        # --- OPTIMIZED LABELING LOGIC ---
        selector = "a[href], button, input:not([type=hidden]), select, textarea, [role='button']"
        
        # This Javascript function is sent to the browser to perform all labeling in one go.
        injected_elements_ids = await page.evaluate(f"""
            (selector) => {{
                const created_ids = [];
                const elements = document.querySelectorAll(selector);
                
                elements.forEach((element, i) => {{
                    if (element.offsetWidth === 0 || element.offsetHeight === 0 || window.getComputedStyle(element).visibility === 'hidden') return;

                    let label_text = element.getAttribute("aria-label") || element.innerText || element.getAttribute("placeholder") || "";
                    label_text = label_text.replace(/\s+/g, ' ').trim();
                    if (label_text.length > 30) label_text = label_text.substring(0, 27) + '...';
                    
                    const display_text = label_text ? `${{i}} (${{label_text}})` : `${{i}}`;

                    const rect = element.getBoundingClientRect();
                    const box = document.createElement('div');
                    const uniqueId = 'ai-toolbox-highlighter-' + Math.random().toString(36).substr(2, 9);
                    box.id = uniqueId;
                    
                    Object.assign(box.style, {{
                        position: 'absolute',
                        border: '2px solid #FF007F',
                        left: `${{window.scrollX + rect.left}}px`,
                        top: `${{window.scrollY + rect.top}}px`,
                        width: `${{rect.width}}px`,
                        height: `${{rect.height}}px`,
                        pointerEvents: 'none',
                        zIndex: '9999',
                        boxSizing: 'border-box'
                    }});

                    const label = document.createElement('span');
                    label.textContent = display_text;
                    
                    Object.assign(label.style, {{
                        position: 'absolute',
                        top: '-10px',
                        left: '-10px',
                        padding: '3px 6px',
                        fontSize: '14px',
                        background: 'rgba(0, 0, 0, 0.75)',
                        color: 'white',
                        fontWeight: 'bold',
                        borderRadius: '5px',
                        fontFamily: 'monospace',
                        whiteSpace: 'nowrap'
                    }});
                    
                    box.appendChild(label);
                    document.body.appendChild(box);
                    created_ids.push(uniqueId);
                }});
                return created_ids;
            }}
        """, selector)

        self.last_labeled_screenshot_bytes = await page.screenshot()

        # Clean up all injected elements in one go
        if injected_elements_ids:
            await page.evaluate("(ids) => ids.forEach(id => document.getElementById(id)?.remove())", injected_elements_ids)

        return {
            "status": "success",
            "active_tab_id": self.active_page_id,
            "url": page.url,
            "message": f"Action completed. Found {len(injected_elements_ids)} interactive elements. Visual state is updated."
        }

    async def run_async(
        self, *, args: dict[str, Any], tool_context: ToolContext
    ) -> Dict[str, Any]:
        await self._ensure_browser_is_ready()
        action = args.get('action', '').upper()
        if not action:
            return {"status": "error", "message": "No action specified."}

        tab_id = args.get('tab_id', self.active_page_id)
        if tab_id not in self.pages:
            if action == 'GOTO':
                page = await self._create_new_page()
            else:
                return {"status": "error", "message": f"Tab with ID {tab_id} not found."}
        else:
            page = self.pages[tab_id]
            await page.bring_to_front()
            self.active_page_id = tab_id

        try:
            if action == 'GOTO':
                url = args.get('url')
                if not url: return {"status": "error", "message": "URL is required for GOTO action."}
                final_url = url
                if not (url.startswith(('http://', 'https://', 'file://'))):
                    cwd = tool_context.state.get('cwd', os.getcwd())
                    absolute_path = os.path.join(cwd, url)
                    if os.path.isfile(absolute_path):
                        final_url = pathlib.Path(absolute_path).as_uri()
                        logger.info(f"Resolved local path '{url}' to URI '{final_url}'")
                    else:
                        return {"status": "error", "message": f"Local file not found at '{absolute_path}'"}
                await page.goto(final_url, wait_until='networkidle', timeout=60000)

            elif action == 'CLICK':
                element_id = args.get('element_id')
                force = args.get('force_click', False)
                if element_id is None: return {"status": "error", "message": "Element ID is required for CLICK action."}

                # Use the *exact* same selector used for labeling to ensure IDs match
                locator = page.locator("a[href], button, input:not([type=hidden]), select, textarea, [role='button']").nth(element_id)
                await locator.click(timeout=30000, force=force)

            elif action == 'TYPE':
                element_id = args.get('element_id')
                text = args.get('text_to_type', '')
                if element_id is None: return {"status": "error", "message": "Element ID is required for TYPE action."}

                # Use the *exact* same selector used for labeling to ensure IDs match
                # Then, filter *after* selecting by index to ensure it's a typeable element
                all_interactive_elements = page.locator("a[href], button, input:not([type=hidden]), select, textarea, [role='button']")
                target_element = all_interactive_elements.nth(element_id)

                # Check the element type after selecting it by its labeled ID
                element_tag = await target_element.evaluate("el => el.tagName.toLowerCase()")
                element_type_attr = await target_element.get_attribute("type")

                # Allow filling only for appropriate input types, textareas, and contenteditables
                is_typeable_input = (
                    element_tag == "input" and element_type_attr not in ["submit", "button", "checkbox", "radio", "file", "image"]
                )
                is_textarea = element_tag == "textarea"
                is_content_editable = await target_element.get_attribute("contenteditable") == "true"

                if not (is_typeable_input or is_textarea or is_content_editable):
                     return {"status": "error", "message": f"Element ID {element_id} is not a typeable field (e.g., input, textarea, contenteditable). It is a '{element_tag}' with type '{element_type_attr}'. Cannot perform TYPE action."}

                await target_element.fill(text)

            elif action == 'SCROLL':
                direction = args.get('scroll_direction')
                if direction not in ['up', 'down']: return {"status": "error", "message": "Scroll direction must be 'up' or 'down'."}
                scroll_expr = f"window.scrollBy(0, window.innerHeight * {'0.95' if direction == 'down' else '-0.95'});"
                await page.evaluate(scroll_expr)

            elif action == 'LIST_TABS':
                return {"status": "success", "tabs": [{"tab_id": id, "url": p.url} for id, p in self.pages.items()]}

            elif action == 'CLOSE_TAB':
                await page.close()
                del self.pages[tab_id]
                if self.active_page_id == tab_id:
                    self.active_page_id = next(iter(self.pages.keys()), None)
                return {"status": "success", "message": f"Tab {tab_id} closed."}

            elif action == 'GET_STATE':
                pass
            else:
                return {"status": "error", "message": f"Unknown action: {action}"}

            await page.wait_for_load_state('networkidle', timeout=30000)
            return await self._update_state_and_screenshots(page, args.get('save_screenshot_path'))

        except Error as e:
            logger.error(f"Playwright error during action '{action}': {e}")
            # Still update state/screenshot on error to show the state *before* the failed action
            await self._update_state_and_screenshots(page)
            return {"status": "error", "message": f"An error occurred: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error during action '{action}': {e}", exc_info=True)
            # Do *not* update state/screenshot here as it might also fail
            return {"status": "error", "message": f"An unexpected error occurred: {str(e)}"}

    async def process_llm_request(
        self, *, tool_context: ToolContext, llm_request: LlmRequest
    ) -> None:
        await super().process_llm_request(tool_context=tool_context, llm_request=llm_request)
        if not self.last_raw_screenshot_bytes or not self.last_labeled_screenshot_bytes:
            return
        
        logger.info("Injecting browser screenshots into the next LLM context.")
        page = self.pages.get(self.active_page_id)
        page_url = page.url if page else "N/A"
        try:
            raw_image_part = types.Part(inline_data=types.Blob(mime_type="image/png", data=self.last_raw_screenshot_bytes))
            labeled_image_part = types.Part(inline_data=types.Blob(mime_type="image/png", data=self.last_labeled_screenshot_bytes))
            llm_request.contents.append(
                types.Content(
                    role='user',
                    parts=[
                        types.Part.from_text(text=f'This is the new state of browser tab {self.active_page_id} at URL: {page_url}\n\nRaw view:'),
                        raw_image_part,
                        types.Part.from_text(text='View with interactive element IDs:'),
                        labeled_image_part,
                    ],
                )
            )
        except Exception as e:
            logger.error(f"Failed to inject screenshots into LLM request: {e}", exc_info=True)
            llm_request.contents.append(
                types.Content(role='user', parts=[types.Part.from_text(text='Note: Error preparing browser screenshots.')])
            )
        finally:
            self.last_raw_screenshot_bytes = None
            self.last_labeled_screenshot_bytes = None

# --- Instantiate and Export Tool ---
browser_tool = AIBrowserTool()
ALL_BROWSER_TOOLS = [browser_tool]
