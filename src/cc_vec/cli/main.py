#!/usr/bin/env python3
"""Main CLI entry point for cc-vec."""

import json
import logging
import os
import sys

import click

from .. import (
    stats as stats_function,
    search as search_function,
    fetch as fetch_function,
    index as index_function,
    list_vector_stores as list_vector_stores_function,
    query_vector_store as query_vector_store_function,
    list_crawls as list_crawls_function,
)
from ..types import FilterConfig, VectorStoreConfig
from ..types.config import load_config
from .filter_options import generate_filter_options, parse_filter_config_from_cli

logger = logging.getLogger(__name__)


@click.group()
@click.option("--debug", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx, debug):
    """cc-vec: Common Crawl Vectorizer CLI"""
    ctx.ensure_object(dict)

    # Skip config loading if just showing help or for commands that don't need it
    if ctx.invoked_subcommand is None or '--help' in sys.argv or '-h' in sys.argv:
        return

    # Commands that don't require environment variables
    no_config_commands = ['list-filter-columns']
    if ctx.invoked_subcommand in no_config_commands:
        return

    # Load configuration from environment variables
    try:
        app_config = load_config()
    except Exception as e:
        click.echo(f"Error loading config: {e}", err=True)
        sys.exit(1)

    # Override log level if debug flag is set
    if debug:
        app_config.logging.level = "DEBUG"

    # Setup logging
    app_config.setup_logging()

    # Store config in context
    ctx.obj["config"] = app_config


@cli.command()
@generate_filter_options
@click.option("--limit", "-l", default=10, help="Maximum number of results")
@click.option(
    "--output",
    "-o",
    type=click.Choice(["json", "text"]),
    default="text",
    help="Output format",
)
@click.pass_context
def search(ctx, limit, output, **filter_kwargs):
    """Search Common Crawl for URLs matching filters.

    At least one filter parameter is recommended for effective searching.
    """
    try:
        # Parse filter config from CLI arguments
        filter_config = parse_filter_config_from_cli(**filter_kwargs)

        # Use the simplified API that handles client initialization
        results = search_function(filter_config, limit=limit)

        if output == "json":
            result = {
                "results": [
                    {
                        "url": str(r.url),  # Convert HttpUrl to string
                        "timestamp": r.timestamp,
                        "status": r.status,
                        "mime_type": r.mime,
                        "length": r.length,
                        "filename": r.filename,
                        "offset": r.offset,
                    }
                    for r in results
                ],
                "total_found": len(results),
                "backend": "athena",
                "crawl_ids": filter_config.crawl_ids,
            }
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"Found {len(results)} results via athena:")
            if filter_config.crawl_ids:
                crawl_display = (
                    ", ".join(filter_config.crawl_ids)
                    if len(filter_config.crawl_ids) > 1
                    else filter_config.crawl_ids[0]
                )
                click.echo(f"Crawl(s): {crawl_display}")
            click.echo()

            for i, result in enumerate(results, 1):
                click.echo(f"{i}. {result.url}")
                click.echo(f"   Status: {result.status}, MIME: {result.mime or 'N/A'}")
                if result.length:
                    click.echo(f"   Length: {result.length:,} bytes")
                click.echo(f"   Timestamp: {result.timestamp}")
                click.echo()

    except Exception as e:
        logger.error("Search failed", exc_info=True)
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@generate_filter_options
@click.option(
    "--output",
    "-o",
    type=click.Choice(["json", "text"]),
    default="text",
    help="Output format",
)
@click.pass_context
def stats(ctx, output, **filter_kwargs):
    """Get statistics for Common Crawl query patterns."""
    try:
        # Parse filter config from CLI arguments
        filter_config = parse_filter_config_from_cli(**filter_kwargs)

        # Use the simplified API that handles client initialization
        response = stats_function(filter_config)

        if output == "json":
            result = {
                "estimated_records": response.estimated_records,
                "estimated_size_mb": response.estimated_size_mb,
                "backend": response.backend,
                "crawl_id": response.crawl_id,
                "estimated_cost_usd": response.estimated_cost_usd,
                "data_scanned_gb": response.data_scanned_gb,
            }
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"Statistics for '{url_pattern}' via {response.backend}:")
            if response.crawl_id:
                click.echo(f"Crawl: {response.crawl_id}")

            click.echo(f"Estimated records: {response.estimated_records:,}")
            click.echo(f"Estimated size: {response.estimated_size_mb:.2f} MB")

            if response.estimated_cost_usd:
                click.echo(f"Athena cost: ${response.estimated_cost_usd:.4f}")
            if response.data_scanned_gb:
                click.echo(f"Data to scan: {response.data_scanned_gb:.2f} GB")

    except Exception as e:
        logger.error("Stats failed", exc_info=ctx.obj["debug"])
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@generate_filter_options
@click.option("--limit", "-l", default=3, help="Maximum number of records to fetch")
@click.option("--max-bytes", default=1024, help="Maximum bytes to display per record")
@click.option("--full", is_flag=True, help="Display full content without truncation")
@click.pass_context
def fetch(ctx, limit, max_bytes, full, **filter_kwargs):
    """Fetch Common Crawl content for URLs matching patterns."""
    try:
        # Parse filter config from CLI arguments
        filter_config = parse_filter_config_from_cli(**filter_kwargs)

        # Use the simplified API that handles client initialization
        results = fetch_function(filter_config, limit=limit)

        click.echo(f"Fetched content for {len(results)} records:")
        click.echo()

        for i, (record, content) in enumerate(results, 1):
            click.echo(f"=== Record {i}: {record.url} ===")
            click.echo(f"Status: {record.status}, MIME: {record.mime or 'N/A'}")
            if record.length:
                click.echo(f"Length: {record.length:,} bytes")
            click.echo(f"Timestamp: {record.timestamp}")
            click.echo(f"S3 Location: {record.filename} at offset {record.offset}")
            click.echo()

            if content:
                # Display processed content (structured data, not raw bytes)
                click.echo("Processed content:")
                click.echo("-" * 40)
                click.echo(f"Title: {content.get('title', 'N/A')}")
                click.echo(
                    f"Meta Description: {content.get('meta_description', 'N/A')}"
                )
                click.echo(f"Word Count: {content.get('word_count', 0)}")
                click.echo(f"Character Count: {content.get('char_count', 0)}")

                # Display the clean text
                text = content.get("text", "")
                if text:
                    if full:
                        click.echo("\nClean Text:")
                        click.echo("-" * 40)
                        click.echo(text)
                    else:
                        # Truncate text for preview
                        preview_text = (
                            text[:max_bytes] if len(text) > max_bytes else text
                        )
                        click.echo("\nClean Text Preview:")
                        click.echo("-" * 40)
                        click.echo(preview_text)
                        if len(text) > max_bytes:
                            click.echo(
                                f"... (truncated, showing {len(preview_text)} of {len(text)} characters)"
                            )
                click.echo("-" * 40)
            else:
                click.echo("❌ Failed to fetch content from S3")

            click.echo()

    except Exception as e:
        logger.error("Fetch failed", exc_info=True)
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--output",
    "-o",
    type=click.Choice(["json", "text"]),
    default="text",
    help="Output format",
)
@click.option(
    "--all",
    is_flag=True,
    help="Show all vector stores, not just cc-vec created ones",
)
@click.pass_context
def list(ctx, output, all):
    """List available OpenAI vector stores."""
    try:
        # Use the simplified API that handles OpenAI key validation
        stores = list_vector_stores_function(cc_vec_only=not all)

        if output == "json":
            click.echo(json.dumps(stores, indent=2))
        else:
            if not stores:
                click.echo("No vector stores found.")
            else:
                click.echo(f"Found {len(stores)} vector store(s):\n")
                for store in stores:
                    click.echo(f"📦 {store['name']}")
                    click.echo(f"   ID: {store['id']}")
                    click.echo(f"   Status: {store['status']}")

                    # Handle file_counts which can be a dict or Pydantic object
                    file_counts = store["file_counts"]
                    if hasattr(file_counts, "total"):
                        total_files = file_counts.total
                    elif isinstance(file_counts, dict):
                        total_files = file_counts.get("total", 0)
                    else:
                        total_files = 0

                    click.echo(f"   Files: {total_files}")
                    click.echo(f"   Size: {store['usage_bytes']:,} bytes")
                    click.echo(f"   Created: {store['created_at']}")
                    click.echo()

    except ValueError as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        logger.error("List failed", exc_info=True)
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--output",
    "-o",
    type=click.Choice(["json", "text"]),
    default="text",
    help="Output format",
)
@click.pass_context
def list_crawls(ctx, output):
    """List available Common Crawl crawls."""
    try:
        # Use the simplified API that handles Athena client initialization
        crawls = list_crawls_function()

        if output == "json":
            click.echo(json.dumps({"crawls": crawls, "total": len(crawls)}, indent=2))
        else:
            if not crawls:
                click.echo("No crawls found.")
            else:
                click.echo(f"Found {len(crawls)} available crawl(s):\n")
                for crawl in crawls:
                    click.echo(f"  • {crawl}")
                click.echo(f"\nTotal: {len(crawls)} crawls")
                click.echo("\nUse these crawl IDs with the --crawl-ids option.")

    except Exception as e:
        logger.error("List crawls failed", exc_info=True)
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--output",
    "-o",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format",
)
def list_filter_columns(output):
    """List all available filter columns from FilterConfig."""
    try:
        columns = []
        for field_name, field_info in FilterConfig.model_fields.items():
            field_type = field_info.annotation
            description = field_info.description or ""

            # Get a simplified type string
            type_str = str(field_type)
            if "List[str]" in type_str:
                type_str = "List[str]"
            elif "List[int]" in type_str:
                type_str = "List[int]"
            elif "str" in type_str:
                type_str = "str"
            else:
                type_str = "various"

            columns.append({
                "name": field_name,
                "type": type_str,
                "description": description,
                "cli_option": f"--{field_name.replace('_', '-')}"
            })

        if output == "json":
            click.echo(json.dumps({"filter_columns": columns}, indent=2))
        else:
            click.echo("Available Filter Columns:")
            click.echo()
            for col in columns:
                click.echo(f"  {col['cli_option']}")
                click.echo(f"    Field: {col['name']}")
                click.echo(f"    Type: {col['type']}")
                if col['description']:
                    click.echo(f"    Description: {col['description']}")
                click.echo()

            click.echo(f"Total: {len(columns)} filter columns available")
            click.echo()
            click.echo("These options are available in: search, stats, fetch, and index commands")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("query")
@click.option("--vector-store-name", help="Name of the vector store to query")
@click.option("--vector-store-id", help="ID of the vector store to query")
@click.option("--limit", "-l", default=5, help="Maximum number of results")
@click.option(
    "--output",
    "-o",
    type=click.Choice(["json", "text"]),
    default="text",
    help="Output format",
)
@click.option("--save", help="Save results to file (for RAG usage)")
@click.pass_context
def query(ctx, query, vector_store_name, vector_store_id, limit, output, save):
    """Query OpenAI vector stores for relevant content.

    Requires either --vector-store-name or --vector-store-id.
    """
    try:
        # Validate that either name or id is provided
        if not vector_store_name and not vector_store_id:
            click.echo(
                "Error: Either --vector-store-name or --vector-store-id is required",
                err=True,
            )
            sys.exit(1)

        # Use the simplified API that handles OpenAI key validation
        # For now, simplified API only takes vector_store_id, so if name is provided,
        # we need to look it up first
        if vector_store_name and not vector_store_id:
            stores = list_vector_stores_function()
            matching_stores = [
                store for store in stores if store["name"] == vector_store_name
            ]
            if not matching_stores:
                click.echo(
                    f"Error: Vector store with name '{vector_store_name}' not found",
                    err=True,
                )
                sys.exit(1)
            vector_store_id = matching_stores[0]["id"]

        results = query_vector_store_function(vector_store_id, query, limit=limit)

        if output == "json":
            click.echo(json.dumps(results, indent=2))
        else:
            click.echo(f"Query results for: '{query}'")
            click.echo(
                f"Vector store: {results.get('vector_store_name', 'Unknown')} ({results['vector_store_id']})"
            )
            click.echo(f"Found {len(results['results'])} relevant result(s):\n")

            for i, result in enumerate(results["results"], 1):
                click.echo(f"=== Result {i} ===")
                click.echo(f"Relevance Score: {result.get('score', 'N/A')}")
                click.echo(f"File ID: {result.get('file_id', 'N/A')}")

                # Extract full content
                content = result.get("content", "")

                # Handle OpenAI Content objects and other types
                if hasattr(content, "text"):
                    # OpenAI Content object
                    content = content.text
                elif hasattr(content, "__iter__") and not isinstance(content, str):
                    # List or other iterable
                    content = " ".join(str(item) for item in content)
                elif not isinstance(content, str):
                    content = str(content)

                # Show full content (no truncation for RAG usage)
                click.echo("\nContent Chunk:")
                click.echo("-" * 60)
                click.echo(content.strip())
                click.echo("-" * 60)

                # Show metadata and citations
                metadata = result.get("metadata", {})
                if metadata:
                    click.echo("\nMetadata:")
                    for key, value in metadata.items():
                        click.echo(f"  {key}: {value}")

                # Show annotations/citations if present
                annotations = result.get("annotations", [])
                if annotations:
                    click.echo(f"\nCitations ({len(annotations)} source(s)):")
                    for j, annotation in enumerate(annotations, 1):
                        if hasattr(annotation, "text"):
                            click.echo(f"  [{j}] {annotation.text}")
                        else:
                            click.echo(f"  [{j}] {annotation}")

                click.echo("\n" + "=" * 80 + "\n")

        # Save results to file if requested
        if save:
            save_data = {
                "query": query,
                "vector_store_id": results["vector_store_id"],
                "vector_store_name": results.get("vector_store_name", "Unknown"),
                "total_results": len(results["results"]),
                "results": results["results"],
            }
            with open(save, "w", encoding="utf-8") as f:
                if output == "json":
                    # For JSON, we need to handle OpenAI objects
                    def serialize_openai_obj(obj):
                        if hasattr(obj, "text"):
                            return obj.text
                        elif hasattr(obj, "__dict__"):
                            return obj.__dict__
                        return str(obj)

                    # Deep convert OpenAI objects to serializable format
                    def convert_results(data):
                        if isinstance(data, dict):
                            return {k: convert_results(v) for k, v in data.items()}
                        elif isinstance(data, list):
                            return [convert_results(item) for item in data]
                        elif hasattr(data, "text"):
                            return data.text
                        elif hasattr(data, "__dict__"):
                            return convert_results(data.__dict__)
                        else:
                            return data

                    converted_data = convert_results(save_data)
                    json.dump(converted_data, f, indent=2, ensure_ascii=False)
                else:
                    # Save as structured text for RAG usage
                    f.write(f"Query: {query}\n")
                    f.write(
                        f"Vector Store: {results.get('vector_store_name', 'Unknown')} ({results['vector_store_id']})\n"
                    )
                    f.write(f"Total Results: {len(results['results'])}\n\n")

                    for i, result in enumerate(results["results"], 1):
                        f.write(f"=== Chunk {i} ===\n")
                        f.write(f"Relevance Score: {result.get('score', 'N/A')}\n")
                        f.write(f"File ID: {result.get('file_id', 'N/A')}\n")

                        # Extract content
                        content = result.get("content", "")
                        if hasattr(content, "text"):
                            content = content.text
                        elif not isinstance(content, str):
                            content = str(content)

                        f.write(f"\nContent:\n{content.strip()}\n")

                        # Add metadata
                        metadata = result.get("metadata", {})
                        if metadata:
                            f.write(f"\nMetadata: {metadata}\n")

                        f.write("\n" + "=" * 60 + "\n\n")

            click.echo(f"\nResults saved to: {save}")

    except ValueError as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        logger.error("Query failed", exc_info=True)
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@generate_filter_options
@click.option(
    "--vector-store-name",
    help="Name for the vector store (auto-generated if not provided)",
)
@click.option("--limit", "-l", default=5, help="Maximum number of records to index")
@click.option(
    "--chunk-size",
    default=800,
    help="Maximum chunk size in tokens for OpenAI chunking (100-4096)",
)
@click.option(
    "--overlap",
    default=400,
    help="Token overlap between chunks (must not exceed half of chunk-size)",
)
@click.option(
    "--output",
    "-o",
    type=click.Choice(["json", "text"]),
    default="text",
    help="Output format",
)
@click.pass_context
def index(ctx, vector_store_name, limit, chunk_size, overlap, output, **filter_kwargs):
    """Index Common Crawl content into OpenAI vector store.

    Requires at least one filter parameter (e.g., --url-patterns, --url-host-names, --crawl-ids).
    Vector store name will be auto-generated if not provided.
    """
    try:
        # Parse filter config from CLI arguments
        filter_config = parse_filter_config_from_cli(**filter_kwargs)

        # Generate vector store name if not provided
        if not vector_store_name:
            import re
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y%m%d_%H%M")

            # Generate name based on available filters
            if filter_config.url_patterns:
                clean_pattern = re.sub(r"[^a-zA-Z0-9_-]", "_", filter_config.url_patterns[0])
                clean_pattern = re.sub(r"_+", "_", clean_pattern).strip("_")
                vector_store_name = f"ccvec_{clean_pattern}_{timestamp}"
            elif filter_config.url_host_names:
                clean_hosts = re.sub(
                    r"[^a-zA-Z0-9_-]", "_", filter_config.url_host_names[0]
                )
                vector_store_name = f"ccvec_{clean_hosts}_{timestamp}"
            elif filter_config.crawl_ids:
                vector_store_name = f"ccvec_{filter_config.crawl_ids[0]}_{timestamp}"
            else:
                vector_store_name = f"ccvec_{timestamp}"

            click.echo(f"Auto-generated vector store name: {vector_store_name}")

        # Construct VectorStoreConfig
        vector_store_config = VectorStoreConfig(
            name=vector_store_name,
            chunk_size=chunk_size,
            overlap=overlap,
        )

        # Use the simplified API that handles all client initialization
        result = index_function(filter_config, vector_store_config, limit=limit)

        if output == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(
                f"Indexed content into vector store '{result['vector_store_name']}':"
            )
            click.echo(f"Vector Store ID: {result['vector_store_id']}")
            click.echo(f"Crawl: {result['crawl']}")
            click.echo()

            click.echo(f"Records processed: {result['total_fetched']}")
            click.echo(f"Successfully fetched: {result['successful_fetches']}")
            click.echo(f"Upload status: {result['upload_status']}")

            if result.get("file_counts"):
                file_counts = result["file_counts"]
                click.echo(f"Files uploaded: {file_counts}")

            if result.get("filenames"):
                click.echo("\nSample filenames:")
                for filename in result["filenames"][:3]:
                    click.echo(f"  - {filename}")
                if len(result["filenames"]) > 3:
                    click.echo(f"  ... and {len(result['filenames']) - 3} more")

            click.echo(
                f"\n✅ Vector store '{result['vector_store_name']}' ready for search!"
            )

    except ValueError as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        logger.error("Index failed", exc_info=True)
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("identifier")
@click.option(
    "--by-name", is_flag=True, help="Delete by vector store name instead of ID"
)
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
@click.option(
    "--output",
    "-o",
    type=click.Choice(["json", "text"]),
    default="text",
    help="Output format",
)
@click.pass_context
def delete(ctx, identifier, by_name, confirm, output):
    """Delete an OpenAI vector store by ID or name.

    IDENTIFIER can be either a vector store ID (vs_xxx) or name (use --by-name flag).
    """
    try:
        from ..api import delete_vector_store, delete_vector_store_by_name

        # Show confirmation unless --confirm flag is used
        if not confirm:
            if by_name:
                click.echo(
                    f"Are you sure you want to delete vector store named '{identifier}'?"
                )
            else:
                click.echo(
                    f"Are you sure you want to delete vector store with ID '{identifier}'?"
                )

            if not click.confirm("This action cannot be undone"):
                click.echo("Deletion cancelled.")
                return

        # Delete the vector store
        if by_name:
            result = delete_vector_store_by_name(identifier)
        else:
            result = delete_vector_store(identifier)

        if output == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            if result.get("deleted", False):
                click.echo(f"✅ Successfully deleted vector store: {result['id']}")
            else:
                click.echo(f"❌ Failed to delete vector store: {result['id']}")

    except ValueError as e:
        if "not found" in str(e).lower():
            click.echo(f"❌ Vector store not found: {identifier}", err=True)
        else:
            click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        logger.error("Delete failed", exc_info=True)
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--mode",
    type=click.Choice(["stdio", "http"]),
    default="stdio",
    help="MCP server mode: stdio for local/pipe communication, http for web/remote access",
)
@click.option("--host", default="127.0.0.1", help="Host to bind to (http mode only)")
@click.option(
    "--port",
    type=int,
    default=1729,
    help="Port to listen on (http mode only, default: 1729)",
)
@click.option(
    "--transport",
    type=click.Choice(["sse", "streamable-http"]),
    default="sse",
    help="HTTP transport protocol (http mode only)",
)
@click.option(
    "--config-file",
    default="mcp-config.json",
    help="Path to write MCP config file (http mode only, default: mcp-config.json)",
)
@click.pass_context
def mcp_serve(ctx, mode, host, port, transport, config_file):
    """Start MCP server for cc-vec tools.

    Supports two modes:
    - stdio: Standard input/output for local MCP clients (default)
    - http: HTTP server for web integrations and remote access

    Examples:
        cc-vec mcp-serve                    # stdio mode (default)
        cc-vec mcp-serve --mode http        # HTTP mode on default port 1729
        cc-vec mcp-serve --mode http --port 8080 --transport sse
    """
    try:
        if mode == "stdio":
            # Use the existing stdio server
            from ..mcp.server import CCVecServer
            import asyncio
            import sys

            # In stdio mode, we must NOT output anything to stdout except JSON-RPC messages
            # Redirect any print/click.echo statements to stderr
            if sys.stdout.isatty():
                # Only show messages if running in a terminal (not from Claude Desktop)
                click.echo("Starting CC-Vec MCP server in stdio mode...", err=True)
                click.echo(
                    "Listening on stdin/stdout for MCP protocol messages", err=True
                )
                click.echo("Press Ctrl+C to stop the server", err=True)

            # Configure logging to stderr BEFORE creating server
            import logging

            logging.basicConfig(
                stream=sys.stderr,
                level=logging.INFO,
                format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                force=True,  # Override any existing configuration
            )

            server = CCVecServer()
            # Don't call server.config.setup_logging() as it might log to stdout
            asyncio.run(server.run())

        elif mode == "http":
            # Use the HTTP server
            from ..mcp.http_server import CCVecHTTPServer
            from pathlib import Path

            click.echo("Starting CC-Vec MCP server in http mode...")
            click.echo(f"Host: {host}")
            click.echo(f"Port: {port}")
            click.echo(f"Transport: {transport}")

            # Determine the server URL based on transport
            if transport == "sse":
                server_url = f"http://{host}:{port}/sse"
                click.echo(f"Server will be available at: {server_url}")
            elif transport == "streamable-http":
                server_url = f"http://{host}:{port}/mcp"
                click.echo(f"Server will be available at: {server_url}")

            # Generate HTTP config (for future Claude Desktop HTTP support)
            http_config = {
                "mcpServers": {
                    "cc-vec-http": {"url": server_url, "transport": transport}
                }
            }

            # Also generate stdio config that proxies to HTTP (for current Claude Desktop)
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(current_dir))
            )

            # For now, use the HTTP config format
            # Claude Desktop may need updates to support HTTP MCP servers directly
            config_to_write = http_config

            # Write config file
            config_path = Path(config_file)
            with open(config_path, "w") as f:
                json.dump(config_to_write, f, indent=2)

            click.echo(f"\n📁 Generated MCP config file: {config_path.absolute()}")
            click.echo("\n⚠️  Claude Desktop only supports stdio MCP servers directly.")
            click.echo("\n📋 For Claude Desktop, you have two options:")
            click.echo("\nOption 1: Use stdio mode (RECOMMENDED)")
            click.echo("-" * 40)
            click.echo(
                "Add this to ~/Library/Application Support/Claude/claude_desktop_config.json:"
            )
            click.echo(
                json.dumps(
                    {
                        "mcpServers": {
                            "cc-vec": {
                                "command": "uv",
                                "args": [
                                    "run",
                                    "--directory",
                                    project_root,
                                    "cc-vec",
                                    "mcp-serve",
                                    "--mode",
                                    "stdio",
                                ],
                                "env": {
                                    "ATHENA_OUTPUT_BUCKET": os.environ.get(
                                        "ATHENA_OUTPUT_BUCKET",
                                        "s3://your-bucket/athena-results/",
                                    ),
                                    "OPENAI_API_KEY": "your-openai-key",
                                },
                            }
                        }
                    },
                    indent=2,
                )
            )

            click.echo("\nOption 2: Use HTTP with proxy bridge")
            click.echo("-" * 40)
            click.echo("First install the proxy: npm install -g mcp-stdio-http-proxy")
            click.echo("Then add this to claude_desktop_config.json:")
            click.echo(
                json.dumps(
                    {
                        "mcpServers": {
                            "cc-vec-http": {
                                "command": "npx",
                                "args": ["mcp-stdio-http-proxy"],
                                "env": {"MCP_SERVER_URL": server_url},
                            }
                        }
                    },
                    indent=2,
                )
            )
            click.echo("\nPress Ctrl+C to stop the server")

            click.echo("DEBUG: About to create CCVecHTTPServer...")
            try:
                server = CCVecHTTPServer(host=host, port=port)
                click.echo("DEBUG: CCVecHTTPServer created successfully")
            except Exception as e:
                click.echo(f"DEBUG: CCVecHTTPServer creation failed: {e}")
                import traceback

                click.echo(f"DEBUG: Traceback: {traceback.format_exc()}")
                raise
            click.echo("DEBUG: About to call server.run()...")
            server.run(transport=transport)
            click.echo("DEBUG: server.run() completed")

    except ImportError as e:
        click.echo("❌ Error: Server dependencies not available", err=True)
        click.echo(f"Details: {e}", err=True)
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\n✅ MCP server stopped by user")
    except Exception as e:
        logger.error(f"MCP server ({mode} mode) failed", exc_info=True)
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


def main():
    """Entry point for cc-vec CLI."""
    cli()


if __name__ == "__main__":
    main()
