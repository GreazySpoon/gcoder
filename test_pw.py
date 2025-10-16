import asyncio
from playwright.async_api import async_playwright
import re

async def get_element_label(element):
    """
    Tries to get a concise, human-readable label for an element.
    """
    label = await element.get_attribute("aria-label") or ""
    if not label:
        label = await element.inner_text()
    if not label and await element.evaluate("el => el.tagName") == "INPUT":
        placeholder = await element.get_attribute("placeholder")
        if placeholder:
            label = placeholder

    if label:
        label = re.sub(r'\s+', ' ', label).strip()
        return label[:25] + '...' if len(label) > 25 else label
    return ""

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        # 1. Set a viewport size that is optimal for most websites and LLM analysis
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        page = await context.new_page()
        
        await page.goto("https://github.com")

        # --- First Screenshot (Without Labels) ---
        print("Taking the first screenshot (raw view)...")
        await page.screenshot(path="screenshot_raw.png")
        print("Saved as 'screenshot_raw.png'")

        # --- Highlighting and Labeling Process ---
        interactive_elements = page.locator(
            "a[href], button, input:not([type=hidden]), select, textarea, [role='button']"
        )
        count = await interactive_elements.count()
        print(f"\nFound {count} interactive elements to label for the second screenshot.")

        for i in range(count):
            element = interactive_elements.nth(i)
            element_context_label = await get_element_label(element)
            
            display_text = f"ID: {i}"
            if element_context_label:
                display_text += f" ({element_context_label})"

            try:
                await element.evaluate(f"""
                    (element, id_text) => {{
                        if (element.offsetWidth === 0 || element.offsetHeight === 0 || 
                            window.getComputedStyle(element).visibility === 'hidden') return;

                        const rect = element.getBoundingClientRect();
                        const box = document.createElement('div');
                        
                        box.style.position = 'absolute';
                        box.style.border = '2px solid #FF007F';
                        box.style.left = `${{window.scrollX + rect.left}}px`;
                        box.style.top = `${{window.scrollY + rect.top}}px`;
                        box.style.width = `${{rect.width}}px`;
                        box.style.height = `${{rect.height}}px`;
                        box.style.pointerEvents = 'none';
                        box.style.zIndex = '9999';
                        box.style.boxSizing = 'border-box';

                        const label = document.createElement('span');
                        label.textContent = id_text;
                        label.style.position = 'absolute';
                        label.style.top = '-10px';
                        label.style.left = '-10px';
                        label.style.padding = '3px 6px';
                        label.style.fontSize = '14px';
                        label.style.background = 'rgba(0, 0, 0, 0.75)';
                        label.style.color = 'white';
                        label.style.fontWeight = 'bold';
                        label.style.borderRadius = '5px';
                        label.style.fontFamily = 'monospace';
                        label.style.boxShadow = '0 2px 5px rgba(0, 0, 0, 0.5)';
                        label.style.whiteSpace = 'nowrap';

                        box.appendChild(label);
                        document.body.appendChild(box);
                    }}
                """, display_text)
            except Exception:
                pass

        # --- Second Screenshot (With Labels) ---
        print("Taking the second screenshot (with labels)...")
        await page.screenshot(path="screenshot_with_labels.png")
        print("Saved as 'screenshot_with_labels.png'")

        await context.close()
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())