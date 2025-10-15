"""CC Fetch handler for MCP server."""

import logging
from typing import Any, Dict, List

from mcp.types import TextContent
from .base import FilterHandler
from ... import fetch as fetch_function
from ..filter_utils import parse_filter_config_from_mcp

logger = logging.getLogger(__name__)


class CCFetchHandler(FilterHandler):
    """Handler for cc_fetch MCP method."""

    def __init__(self, api_method=None):
        super().__init__(api_method)

    async def handle(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle cc_fetch tool calls."""
        limit = args.get("limit", 3)
        max_bytes = args.get("max_bytes", 1024)

        # Parse FilterConfig from MCP arguments
        filter_config = parse_filter_config_from_mcp(args)

        try:
            results = fetch_function(filter_config, limit=limit)

            if not results:
                response_text = "No content fetched for specified filters"
                return [TextContent(type="text", text=response_text)]

            response_text = f"Fetched content for {len(results)} records:\n\n"

            for i, (record, content) in enumerate(results, 1):
                response_text += f"=== Record {i}: {record.url} ===\n"
                response_text += (
                    f"Status: {record.status}, MIME: {record.mime or 'N/A'}\n"
                )
                if record.length:
                    response_text += f"Length: {record.length:,} bytes\n"
                response_text += f"Timestamp: {record.timestamp}\n"
                response_text += (
                    f"S3 Location: {record.filename} at offset {record.offset}\n\n"
                )

                if content:
                    response_text += "Processed content:\n"
                    response_text += "-" * 40 + "\n"
                    response_text += f"Title: {content.get('title', 'N/A')}\n"
                    response_text += f"Word count: {content.get('word_count', 'N/A')}\n"
                    response_text += f"Language: {content.get('language', 'N/A')}\n"
                    response_text += f"Chunks: {len(content.get('chunks', []))}\n\n"

                    text_content = content.get("text", "")
                    if text_content:
                        display_text = text_content[:max_bytes]
                        response_text += f"Text preview ({len(text_content)} chars):\n"
                        response_text += display_text
                        if len(text_content) > max_bytes:
                            response_text += f"\n... (truncated, showing {max_bytes} of {len(text_content)} characters)\n"
                        response_text += "\n"
                    response_text += "-" * 40 + "\n"
                else:
                    response_text += "❌ Failed to process content\n"

                response_text += "\n"

            return [TextContent(type="text", text=response_text)]

        except Exception as e:
            error_text = f"Fetch failed: {str(e)}"
            logger.error(error_text)
            return [TextContent(type="text", text=error_text)]
