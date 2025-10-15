"""Base handler class for MCP methods."""

import logging
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Callable,
    get_type_hints,
    get_args,
    Literal,
    Union,
)
from abc import ABC, abstractmethod
import inspect

from mcp.types import TextContent, Tool
from ..filter_utils import generate_filter_properties

logger = logging.getLogger(__name__)


class BaseHandler(ABC):
    """Base class for MCP method handlers."""

    def __init__(
        self,
        api_method: Optional[Callable] = None,
    ):
        """Initialize handler with API method.

        Args:
            api_method: The API function this handler wraps
        """
        self.api_method = api_method

    def get_tool_definition(self, tool_name: str, description: str) -> Tool:
        """Generate MCP tool definition from API method signature and docstring.

        Args:
            tool_name: Name for the MCP tool
            description: Description of what the tool does

        Returns:
            Tool definition with schema derived from API method
        """
        if not self.api_method:
            raise ValueError(f"No api_method set for handler {self.__class__.__name__}")

        return Tool(
            name=tool_name,
            description=description,
            inputSchema=self._generate_tool_schema(self.api_method),
        )

    def _generate_tool_schema(self, func) -> Dict[str, Any]:
        """Generate OpenAI tool schema from a Python function's type hints and docstring."""
        hints = get_type_hints(func)
        sig = inspect.signature(func)
        doc = inspect.getdoc(func)

        param_desc = {}
        if doc:
            lines = doc.split("\n")
            in_args_section = False
            for line in lines:
                line = line.strip()
                if line.startswith("Args:"):
                    in_args_section = True
                    continue
                elif line.startswith("Returns:") or line.startswith("Raises:"):
                    in_args_section = False
                    continue

                if in_args_section and ":" in line:
                    if "(" in line and ")" in line:
                        param_part = line.split("(")[0].strip()
                        desc_part = line.split("):", 1)
                        if len(desc_part) > 1:
                            param_desc[param_part] = desc_part[1].strip()
                    else:
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            param_desc[parts[0].strip()] = parts[1].strip()

        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name in ["self"]:
                continue

            param_type = hints.get(param_name, str)

            if hasattr(param_type, "__origin__") and param_type.__origin__ is Literal:
                properties[param_name] = {
                    "type": "string",
                    "enum": list(get_args(param_type)),
                    "description": param_desc.get(
                        param_name, self._get_default_param_description(param_name)
                    ),
                }
            elif hasattr(param_type, "__origin__") and param_type.__origin__ is Union:
                args = get_args(param_type)
                if len(args) == 2 and type(None) in args:
                    non_none_type = args[0] if args[1] is type(None) else args[1]
                    schema_info = self._python_type_to_schema(non_none_type)
                    properties[param_name] = {
                        **schema_info,
                        "description": param_desc.get(
                            param_name, self._get_default_param_description(param_name)
                        ),
                    }
                else:
                    properties[param_name] = {
                        "type": "string",
                        "description": param_desc.get(
                            param_name, self._get_default_param_description(param_name)
                        ),
                    }
            elif hasattr(param_type, "__origin__") and param_type.__origin__ is list:
                args = get_args(param_type)
                if args:
                    item_schema = self._python_type_to_schema(args[0])
                    properties[param_name] = {
                        "type": "array",
                        "items": item_schema,
                        "description": param_desc.get(
                            param_name, self._get_default_param_description(param_name)
                        ),
                    }
                else:
                    properties[param_name] = {
                        "type": "array",
                        "description": param_desc.get(
                            param_name, self._get_default_param_description(param_name)
                        ),
                    }
            else:
                schema_info = self._python_type_to_schema(param_type)
                properties[param_name] = {
                    **schema_info,
                    "description": param_desc.get(
                        param_name, self._get_default_param_description(param_name)
                    ),
                }

            if param.default == inspect.Parameter.empty:
                required.append(param_name)
            elif param.default is not None:
                properties[param_name]["default"] = param.default

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def _python_type_to_schema(self, python_type) -> Dict[str, Any]:
        """Convert Python type annotation to JSON schema type."""
        type_map = {
            str: {"type": "string"},
            int: {"type": "integer"},
            float: {"type": "number"},
            bool: {"type": "boolean"},
            dict: {"type": "object"},
            list: {"type": "array"},
        }

        return type_map.get(python_type, {"type": "string"})

    def _get_default_param_description(self, param_name: str) -> str:
        """Generate default description for parameter based on name."""
        descriptions = {
            "url_pattern": 'URL pattern to search (e.g., "%.github.io%", "%.example.com%")',
            "limit": "Maximum number of results",
            "crawl": "Common Crawl dataset to use (default: CC-MAIN-2024-33)",
            "status_codes": "HTTP status codes to filter by (e.g., [200, 201])",
            "mime_types": 'MIME types to filter by (e.g., ["text/html", "text/plain"])',
            "languages": 'Languages to filter by (e.g., ["en", "es", "isl"])',
            "date_from": "Start date filter (format: yyyy, yyyyMM, or yyyyMMdd)",
            "date_to": "End date filter (format: yyyy, yyyyMM, or yyyyMMdd)",
            "custom_filters": "Additional CDX filter strings",
            "vector_store_name": "Name for the vector store to create or query",
            "vector_store_id": "ID of the vector store to query",
            "query": "Query text to search for",
            "chunk_size": "Maximum chunk size in tokens (100-4096, default: 800)",
            "overlap": "Token overlap between chunks (default: 400, max: half of chunk_size)",
            "max_bytes": "Maximum characters to display per record (default: 1024)",
            "cc_vec_only": "If true, only show vector stores created by cc-vec (default: true)",
        }

        return descriptions.get(param_name, f"{param_name.replace('_', ' ').title()}")

    @abstractmethod
    async def handle(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle the MCP method request.

        Args:
            args: Method arguments

        Returns:
            List of TextContent responses
        """
        pass


class FilterHandler(BaseHandler):
    """Base handler for tools that accept FilterConfig parameters.

    This handler dynamically generates tool schema properties from FilterConfig
    and merges them with any additional parameters defined in the API method signature.
    """

    def _generate_tool_schema(self, func) -> Dict[str, Any]:
        """Generate tool schema with FilterConfig properties merged with other parameters."""
        # Get the standard schema from the parent class
        base_schema = super()._generate_tool_schema(func)

        # Generate FilterConfig properties
        filter_properties = generate_filter_properties()

        # Merge filter properties into the schema
        # FilterConfig fields are always optional, so don't add to required
        base_schema["properties"].update(filter_properties)

        return base_schema
