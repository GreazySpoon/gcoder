import os
from pathlib import Path
from configparser import ConfigParser

# Default configuration to be written if the file doesn't exist.
DEFAULT_CONFIG = """
[default]
# The active LLM provider.
# Supported values: ollama, openai, gemini, vllm
active_provider = ollama
# Set to true to enable step-by-step confirmation for sensitive commands in the CLI.
human_in_the_loop = false

[ollama]
# The host for your Ollama instance (e.g., http://localhost:11434)
host = http://10.10.60.28:11434
# Your specific Ollama model name for the basic agent
model = qwen3-30-8:latest
# The model to use for the more complex autonomous agent workflow
autonomous_model = qwen3-30-8:latest

[openai]
# Model names from OpenAI (e.g., gpt-4o, gpt-3.5-turbo)
# Your OPENAI_API_KEY must be set as an environment variable.
model = gpt-4o
autonomous_model = gpt-4o

[gemini]
# Model names from Google AI Studio (e.g., gemini-1.5-flash-latest, gemini-1.5-pro-latest)
# Your GOOGLE_API_KEY must be set as an environment variable.
model = gemini-1.5-flash-latest
autonomous_model = gemini-1.5-pro-latest

[vllm]
# The host for your vLLM OpenAI-compatible endpoint (e.g., http://localhost:8000/v1)
host = http://localhost:8000/v1
# The model name as served by your vLLM instance
model = meta-llama/Meta-Llama-3-8B-Instruct
autonomous_model = meta-llama/Meta-Llama-3-8B-Instruct
# API key for the vLLM endpoint, if required. Set to "none" if not needed.
# It's recommended to set this as an environment variable instead (e.g., VLLM_API_KEY).
api_key = none
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