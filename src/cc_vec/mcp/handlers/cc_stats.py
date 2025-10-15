"""CC Stats handler for MCP server."""

import logging
from typing import Any, Dict, List

from mcp.types import TextContent
from .base import FilterHandler
from ... import stats as stats_function
from ..filter_utils import parse_filter_config_from_mcp

logger = logging.getLogger(__name__)


class CCStatsHandler(FilterHandler):
    """Handler for cc_stats MCP method."""

    def __init__(self, api_method=None):
        super().__init__(api_method)

    async def handle(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle cc_stats tool calls."""
        # Parse FilterConfig from MCP arguments
        filter_config = parse_filter_config_from_mcp(args)

        try:
            response = stats_function(filter_config)

            backend_info = f"via {response.backend.title()}"
            if response.crawl_id:
                backend_info += f" - {response.crawl_id}"

            response_text = f"Statistics for specified filters ({backend_info}):\n\n"

            if response.backend == "athena":
                response_text += f"Data to scan: {response.data_scanned_gb:.2f} GB\n"
                response_text += f"Athena cost: ${response.estimated_cost_usd:.4f}\n"
                response_text += f"Estimated records: ~{response.estimated_records:,}\n"
                response_text += (
                    "\n💡 Athena provides more reliable access than CDX HTTP API"
                )
            else:
                response_text += f"Estimated records: {response.estimated_records:,}\n"
                response_text += (
                    f"Estimated size: {response.estimated_size_mb:.2f} MB\n"
                )
                response_text += (
                    "\n⚠️ CDX HTTP API can be unreliable - consider using Athena"
                )

            return [TextContent(type="text", text=response_text)]

        except Exception as e:
            error_text = f"Statistics calculation failed: {str(e)}"
            return [TextContent(type="text", text=error_text)]
