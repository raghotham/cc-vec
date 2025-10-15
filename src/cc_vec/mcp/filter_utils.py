"""Dynamic MCP property generation from FilterConfig."""

from typing import get_args, get_origin, Any, Dict
from ..types import FilterConfig


def generate_filter_properties() -> Dict[str, Any]:
    """Generate MCP tool input schema properties from FilterConfig fields.

    Returns:
        Dictionary of property definitions suitable for MCP tool inputSchema
    """
    properties = {}

    for field_name, field_info in FilterConfig.model_fields.items():
        # Get field metadata
        field_type = field_info.annotation
        description = field_info.description or f"Filter by {field_name}"

        # Determine if this is Optional type
        origin = get_origin(field_type)
        inner_type = field_type
        if origin is type(None) or (hasattr(field_type, '__args__') and type(None) in get_args(field_type)):
            # Extract the non-None type
            args = get_args(field_type)
            if args:
                inner_type = args[0] if args[0] is not type(None) else (args[1] if len(args) > 1 else str)

        # Check if inner type is List
        inner_origin = get_origin(inner_type)
        if inner_origin is list:
            # Get the list element type
            list_args = get_args(inner_type)
            element_type = list_args[0] if list_args else str

            # Generate array schema
            if element_type is int:
                properties[field_name] = {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": description,
                }
            else:
                properties[field_name] = {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": description,
                }
        else:
            # Scalar type
            if inner_type is int:
                properties[field_name] = {
                    "type": "integer",
                    "description": description,
                }
            elif inner_type is bool:
                properties[field_name] = {
                    "type": "boolean",
                    "description": description,
                }
            else:
                properties[field_name] = {
                    "type": "string",
                    "description": description,
                }

    return properties


def parse_filter_config_from_mcp(args: Dict[str, Any]) -> FilterConfig:
    """Parse MCP arguments into a FilterConfig object.

    Args:
        args: Dictionary of arguments from MCP tool call

    Returns:
        FilterConfig object with parsed values
    """
    parsed = {}

    for field_name, field_info in FilterConfig.model_fields.items():
        # Get value from args
        value = args.get(field_name)

        if value is None:
            continue

        # Pass through as-is - MCP already provides the correct types
        # (arrays as arrays, strings as strings, etc.)
        parsed[field_name] = value

    return FilterConfig(**parsed)
