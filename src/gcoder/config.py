# src/gcoder/config.py

import os
from pathlib import Path
from configparser import ConfigParser

# Default configuration to be written if the file doesn't exist.
DEFAULT_CONFIG = """
[default]
# Set to true to enable step-by-step confirmation for sensitive commands in the CLI.
human_in_the_loop = false

[ollama]
# Your specific Ollama model name for the basic agent
model = qwen3-30-8:latest
# The model to use for the more complex autonomous agent workflow
autonomous_model = qwen3-30-8:latest
# The host for your Ollama instance
host = http://10.10.60.28:11434
"""

class ConfigManager:
    """
    A simple manager to read settings from the config.ini file.
    """
    def __init__(self):
        self.config_dir = Path.home() / ".gcoder"
        self.config_path = self.config_dir / "config.ini"
        self.config = ConfigParser()
        self.config_dir.mkdir(exist_ok=True)
        
        if not self.config_path.exists():
            self._create_default_config()
        
        self.config.read(self.config_path)

    def _create_default_config(self):
        """Writes the default config file."""
        with open(self.config_path, "w") as f:
            f.write(DEFAULT_CONFIG)
        print(f"Created default config file at: {self.config_path}")

    def get(self, section, key, fallback=None):
        """Gets a value from the config."""
        return self.config.get(section, key, fallback=fallback)

    def getboolean(self, section, key, fallback=False):
        """Gets a boolean value from the config."""
        return self.config.getboolean(section, key, fallback=fallback)

# Create a single, shared instance to be imported by other modules
config = ConfigManager()