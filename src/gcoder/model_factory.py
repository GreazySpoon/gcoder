import os
from typing import Union, Dict, Any

from google.adk.models.lite_llm import LiteLlm
from gcoder.config import config

def get_model_instance(use_case: str) -> Union[str, LiteLlm]:
    """
    Creates and configures the appropriate LLM model instance based on the
    active provider in the configuration file.

    Args:
        use_case: Either 'basic' for the standard agent or 'autonomous' for the
                  more complex agent workflow.

    Returns:
        A model instance compatible with the ADK LlmAgent (either a string for
        native providers like Gemini or a LiteLlm wrapper instance).
    """
    provider = config.get('default', 'active_provider', fallback='ollama').lower()
    model_key = 'autonomous_model' if use_case == 'autonomous' else 'model'

    if provider == 'ollama':
        model_name = config.get('ollama', model_key)
        host = config.get('ollama', 'host')
        os.environ['OLLAMA_API_BASE'] = host
        return LiteLlm(model=f"ollama_chat/{model_name}")

    elif provider == 'openai':
        model_name = config.get('openai', model_key)
        # Assumes OPENAI_API_KEY is set in the environment
        return LiteLlm(model=f"openai/{model_name}")

    elif provider == 'gemini':
        model_name = config.get('gemini', model_key)
        # ADK uses google-genai library, which reads GOOGLE_API_KEY from env
        # Set this flag to ensure it uses the AI Studio endpoint, not Vertex AI
        os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = 'FALSE'
        # ADK's native Gemini integration works by passing the model name string directly
        return model_name

    elif provider == 'vllm':
        model_name = config.get('vllm', model_key)
        host = config.get('vllm', 'host')
        api_key = config.get('vllm', 'api_key', fallback='none')
        
        # LiteLLM uses these env vars for custom OpenAI-compatible endpoints
        os.environ['OPENAI_API_BASE'] = host
        if api_key and api_key.lower() != 'none':
            os.environ['OPENAI_API_KEY'] = api_key
        else:
            os.environ['OPENAI_API_KEY'] = "DUMMY_KEY" # LiteLLM requires a key

        # The model string for LiteLLM should still be prefixed for OpenAI compatibility
        return LiteLlm(model=f"openai/{model_name}", api_base=host)

    else:
        raise ValueError(f"Unsupported provider '{provider}' in configuration.")