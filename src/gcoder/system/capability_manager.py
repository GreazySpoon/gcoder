# src/gcoder/system/capability_manager.py

import shutil
from typing import Set

LSP_SERVERS = {
    "python": "pyright-langserver",
    "csharp": "omnisharp",
    "typescript": "typescript-language-server"
}

class CapabilityManager:
    """
    Detects available system dependencies like Git and LSP servers.
    """
    def __init__(self):
        self.has_git: bool = False
        self.supported_lsp_languages: Set[str] = set()
        self._check_capabilities()

    def _check_capabilities(self):
        """Uses shutil.which to find executables in the system's PATH."""
        self.has_git = shutil.which("git") is not None
        
        for lang, executable in LSP_SERVERS.items():
            if shutil.which(executable):
                self.supported_lsp_languages.add(lang)

    @property
    def is_lsp_supported(self) -> bool:
        """Returns True if at least one supported LSP server is found."""
        return bool(self.supported_lsp_languages)