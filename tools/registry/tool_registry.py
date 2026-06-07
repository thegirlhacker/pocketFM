import inspect
import json
from typing import Callable, Dict, Any

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Callable] = {}

    def register(self, name: str, tool_func: Callable):
        """Registers a tool function with the given name."""
        self._tools[name] = tool_func

    def get_tool(self, name: str) -> Callable | None:
        """Retrieves a registered tool by name."""
        return self._tools.get(name)

    def execute_tool(self, name: str, args: Dict[str, Any]) -> str:
        """Executes a tool with the provided arguments."""
        tool_func = self.get_tool(name)
        if not tool_func:
            return f"Error: Tool '{name}' not found."
        
        try:
            result = tool_func(**args)
            
            if isinstance(result, (dict, list)):
                return json.dumps(result, indent=2)
            return str(result)
        except TypeError as e:
             return f"Error: Invalid arguments for tool '{name}'. Details: {e}"
        except Exception as e:
             return f"Error executing tool '{name}': {e}"

    def get_all_tool_descriptions(self) -> str:
        """Generates a string describing all registered tools, their signatures, and docstrings."""
        if not self._tools:
            return "No tools available."
        
        descriptions = []
        for name, func in self._tools.items():
            sig = inspect.signature(func)
            doc = func.__doc__ or "No description provided."
            # Clean up docstring indentation
            doc = "\n    ".join([line.strip() for line in doc.strip().split("\n")])
            descriptions.append(f"{len(descriptions)+1}. {name}{sig}:\n    {doc}")
            
        return "\n\n".join(descriptions)
