class LLMClient:
    """Agnostic LLM wrapper (Makes it easy to swap OpenAI/Anthropic)"""
    def __init__(self):
        pass

    def generate(self, prompt: str, system: str = "") -> str:
        return ""
