"""CC Index handler for MCP server."""

import logging
from typing import Any, Dict, List

from mcp.types import TextContent
from .base import FilterHandler
from ... import index as index_function
from ...types import VectorStoreConfig
from ..filter_utils import parse_filter_config_from_mcp

logger = logging.getLogger(__name__)


class CCIndexHandler(FilterHandler):
    """Handler for cc_index MCP method."""

    def __init__(self, api_method=None):
        super().__init__(api_method)

    async def handle(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle cc_index tool calls."""
        vector_store_name = args.get("vector_store_name")
        limit = args.get("limit", 5)
        chunk_size = args.get("chunk_size", 800)
        overlap = args.get("overlap", 400)

        # Parse FilterConfig from MCP arguments
        filter_config = parse_filter_config_from_mcp(args)

        # Generate vector store name if not provided
        if not vector_store_name:
            import re
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            if filter_config.url_patterns:
                clean_pattern = re.sub(r"[^a-zA-Z0-9_-]", "_", filter_config.url_patterns[0])
                clean_pattern = re.sub(r"_+", "_", clean_pattern).strip("_")
                vector_store_name = f"ccvec_{clean_pattern}_{timestamp}"
            elif filter_config.url_host_names:
                clean_hosts = re.sub(r"[^a-zA-Z0-9_-]", "_", filter_config.url_host_names[0])
                vector_store_name = f"ccvec_{clean_hosts}_{timestamp}"
            elif filter_config.crawl_ids:
                vector_store_name = f"ccvec_{filter_config.crawl_ids[0]}_{timestamp}"
            else:
                vector_store_name = f"ccvec_{timestamp}"

        # Construct VectorStoreConfig
        vector_store_config = VectorStoreConfig(
            name=vector_store_name,
            chunk_size=chunk_size,
            overlap=overlap,
        )

        try:
            result = index_function(filter_config, vector_store_config, limit=limit)

            if result.get("upload_status") == "no_content":
                response_text = "No content found for specified filters"
                return [TextContent(type="text", text=response_text)]

            response_text = f"Successfully loaded content into vector store '{result['vector_store_name']}':\n\n"
            response_text += f"Vector Store ID: {result['vector_store_id']}\n"
            if result.get("crawl"):
                response_text += f"Crawl: {result['crawl']}\n"
            response_text += "\n"

            response_text += f"Records processed: {result['total_fetched']}\n"
            response_text += f"Successfully fetched: {result['successful_fetches']}\n"
            response_text += f"Upload status: {result['upload_status']}\n"

            if result.get("file_counts"):
                file_counts = result["file_counts"]
                response_text += f"Files uploaded: {file_counts}\n"

            if result.get("filenames"):
                response_text += "\nSample filenames:\n"
                for filename in result["filenames"][:3]:
                    response_text += f"  - {filename}\n"
                if len(result["filenames"]) > 3:
                    response_text += f"  ... and {len(result['filenames']) - 3} more\n"

            response_text += (
                f"\n✅ Vector store '{result['vector_store_name']}' ready for search!\n"
            )

            return [TextContent(type="text", text=response_text)]

        except Exception as e:
            error_text = f"Index failed: {str(e)}"
            logger.error(error_text)
            return [TextContent(type="text", text=error_text)]
