"""CC Search handler for MCP server."""

import logging
from typing import Any, Dict, List

from mcp.types import TextContent
from .base import FilterHandler
from ... import search as search_function
from ..filter_utils import parse_filter_config_from_mcp

logger = logging.getLogger(__name__)


class CCSearchHandler(FilterHandler):
    """Handler for cc_search MCP method."""

    def __init__(self, api_method=None):
        super().__init__(api_method)

    async def handle(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle cc_search tool calls."""
        limit = args.get("limit", 10)

        # Parse FilterConfig from MCP arguments
        filter_config = parse_filter_config_from_mcp(args)

        try:
            results = search_function(filter_config, limit=limit)

            if not results:
                response_text = "SEARCH RESULTS: 0 URLs found for specified filters"
                return [TextContent(type="text", text=response_text)]

            summary = f"SEARCH RESULTS: Found {len(results)} URLs for specified filters"

            url_list = "\n\nURL LIST:"
            for i, record in enumerate(results, 1):
                url_list += f"\n{i}. {record.url}"
                url_list += f"\n   - Status: {record.status}"
                url_list += f"\n   - MIME: {record.mime or 'N/A'}"
                url_list += f"\n   - Timestamp: {record.timestamp}"
                if record.length:
                    url_list += f"\n   - Size: {record.length:,} bytes"
                url_list += "\n"

            metadata = "\n\nSUMMARY:"
            metadata += f"\n- Total URLs found: {len(results)}"

            # Show active filters
            if filter_config.url_patterns:
                metadata += f"\n- URL patterns: {', '.join(filter_config.url_patterns)}"
            if filter_config.url_host_names:
                metadata += f"\n- Hostnames: {', '.join(filter_config.url_host_names)}"
            if filter_config.url_host_tlds:
                metadata += f"\n- TLDs: {', '.join(filter_config.url_host_tlds)}"
            if filter_config.url_host_registered_domains:
                metadata += f"\n- Registered domains: {', '.join(filter_config.url_host_registered_domains)}"
            if filter_config.crawl_ids:
                metadata += f"\n- Crawl IDs: {', '.join(filter_config.crawl_ids)}"
            metadata += f"\n- Limit applied: {limit}"

            if limit < 100:
                metadata += "\n- Note: Increase limit (max 100) to see more results"

            response_text = summary + url_list + metadata

            return [TextContent(type="text", text=response_text)]

        except Exception as e:
            error_text = f"Search failed: {str(e)}"
            logger.error(error_text)
            return [TextContent(type="text", text=error_text)]
