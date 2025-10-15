"""Dynamic CLI option generation from FilterConfig."""

import click
from typing import get_args, get_origin, Any
from ..types import FilterConfig


def generate_filter_options(func):
    """Decorator that dynamically adds CLI options from FilterConfig fields.

    This reads the FilterConfig Pydantic model and generates click options
    for each field, handling type conversions and defaults automatically.
    """
    # Iterate in reverse so options appear in correct order
    for field_name, field_info in reversed(list(FilterConfig.model_fields.items())):
        # Convert field_name to CLI format (e.g., url_patterns -> --url-patterns)
        option_name = f"--{field_name.replace('_', '-')}"

        # Get field metadata
        field_type = field_info.annotation
        field_default = field_info.default
        description = field_info.description or f"Filter by {field_name}"

        # Determine if this is Optional[List[X]]
        origin = get_origin(field_type)

        # Handle Optional types (Union with None)
        is_optional = False
        inner_type = field_type
        if origin is type(None) or (hasattr(field_type, '__args__') and type(None) in get_args(field_type)):
            is_optional = True
            # Extract the non-None type
            args = get_args(field_type)
            if args:
                inner_type = args[0] if args[0] is not type(None) else (args[1] if len(args) > 1 else str)

        # Check if inner type is List
        inner_origin = get_origin(inner_type)
        if inner_origin is list:
            # It's a List type, we'll pass comma-separated strings
            description += " (comma-separated)"
            func = click.option(option_name, help=description, type=str, default=None)(func)
        else:
            # Scalar type
            func = click.option(option_name, help=description, type=str, default=None)(func)

    return func


def parse_filter_config_from_cli(**kwargs) -> FilterConfig:
    """Parse CLI arguments into a FilterConfig object.

    Handles type conversions:
    - Comma-separated strings to List[str]
    - Comma-separated numbers to List[int]
    - None values properly
    """
    parsed = {}

    for field_name, field_info in FilterConfig.model_fields.items():
        # Get value from kwargs (CLI uses dashes, we use underscores)
        cli_name = field_name
        value = kwargs.get(cli_name)

        if value is None:
            continue

        # Get field type info
        field_type = field_info.annotation
        origin = get_origin(field_type)

        # Handle Optional types
        inner_type = field_type
        if origin is type(None) or (hasattr(field_type, '__args__') and type(None) in get_args(field_type)):
            args = get_args(field_type)
            if args:
                inner_type = args[0] if args[0] is not type(None) else (args[1] if len(args) > 1 else str)

        # Check if inner type is List
        inner_origin = get_origin(inner_type)
        if inner_origin is list:
            # Get the list element type
            list_args = get_args(inner_type)
            element_type = list_args[0] if list_args else str

            # Parse comma-separated values
            if isinstance(value, str):
                items = [x.strip() for x in value.split(",")]

                # Convert to appropriate type
                if element_type is int:
                    parsed[field_name] = [int(x) for x in items]
                else:
                    parsed[field_name] = items
            elif isinstance(value, list):
                parsed[field_name] = value
        else:
            # Scalar value
            parsed[field_name] = value

    return FilterConfig(**parsed)
