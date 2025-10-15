"""Simplified AWS Athena client for Common Crawl queries."""

import logging
import re
from typing import List, Optional

import boto3
from botocore.exceptions import NoCredentialsError, BotoCoreError

from ..types import AthenaSettings, CrawlRecord, FilterConfig


logger = logging.getLogger(__name__)


class AthenaQueryError(Exception):
    """Exception raised for Athena query errors."""

    pass


class CrawlQueryBuilder:
    """Query builder for Common Crawl ccindex table with SQL injection protection."""

    def __init__(
        self,
        filter_config: FilterConfig,
        limit: Optional[int] = None,
    ):
        """Initialize query builder.

        Args:
            filter_config: FilterConfig with search criteria (including crawl_ids)
            limit: Maximum number of results
        """
        self.filter_config = filter_config
        self.limit = limit
        self.database = "ccindex"
        self.table = "ccindex"

    @staticmethod
    def _parse_url_pattern(pattern: str) -> dict:
        """Parse URL pattern to extract optimized column filters.

        Analyzes URL patterns to determine which indexed columns can be used
        for better query performance in Athena.

        Pattern types:
        - `*.va` → url_host_tld = 'va'
        - `example.com` → url_host_tld = 'com' AND url_host_name IN ('example.com', 'www.example.com')
        - `*.example.com` → url_host_tld = 'com' AND url_host_registered_domain = 'example.com'
        - `example.com/blog/*` → url_host_tld = 'com' AND url_host_name = 'example.com' AND url_path LIKE '/blog/%'

        Args:
            pattern: URL pattern (supports * wildcards)

        Returns:
            Dictionary with extracted filters:
            {
                'tld': str,
                'registered_domain': str,
                'host_name': str,
                'path': str,
                'use_fallback': bool  # True if pattern is too complex for optimization
            }
        """
        # Convert * wildcards to % for SQL LIKE
        sql_pattern = pattern.replace("*", "%")

        # Initialize result
        result = {
            'tld': None,
            'registered_domain': None,
            'host_name': None,
            'path': None,
            'use_fallback': False
        }

        # Pattern 1: TLD-only pattern (*.va)
        tld_only_match = re.match(r'^%?\.([a-z]{2,})$', sql_pattern, re.IGNORECASE)
        if tld_only_match:
            result['tld'] = tld_only_match.group(1)
            return result

        # Pattern 2: Exact domain (example.com) - extract domain and TLD
        exact_domain_match = re.match(r'^([a-z0-9-]+)\.([a-z]{2,})$', sql_pattern, re.IGNORECASE)
        if exact_domain_match:
            domain = exact_domain_match.group(1)
            tld = exact_domain_match.group(2)
            result['tld'] = tld
            result['host_name'] = f"{domain}.{tld}"
            return result

        # Pattern 3: Subdomain wildcard (%.example.com or *.example.com)
        subdomain_wildcard_match = re.match(r'^%\.([a-z0-9-]+)\.([a-z]{2,})$', sql_pattern, re.IGNORECASE)
        if subdomain_wildcard_match:
            domain = subdomain_wildcard_match.group(1)
            tld = subdomain_wildcard_match.group(2)
            result['tld'] = tld
            result['registered_domain'] = f"{domain}.{tld}"
            return result

        # Pattern 4: Domain with path (example.com/blog/% or example.com/blog/*)
        domain_with_path_match = re.match(r'^([a-z0-9-]+)\.([a-z]{2,})(/.*)$', sql_pattern, re.IGNORECASE)
        if domain_with_path_match:
            domain = domain_with_path_match.group(1)
            tld = domain_with_path_match.group(2)
            path = domain_with_path_match.group(3)
            result['tld'] = tld
            result['host_name'] = f"{domain}.{tld}"
            result['path'] = path
            return result

        # If pattern doesn't match any optimization pattern, use fallback
        result['use_fallback'] = True
        return result

    @staticmethod
    def _escape_sql_string(value: str) -> str:
        """Escape SQL string to prevent injection attacks.

        Args:
            value: String value to escape

        Returns:
            Escaped string safe for SQL
        """
        if not isinstance(value, str):
            raise ValueError(f"Expected string, got {type(value)}")

        dangerous_patterns = [
            r";",  # Statement separators
            r"--",  # SQL comments
            r"/\*",  # Block comments
            r"\*/",  # Block comments
            r"\bUNION\b",  # Union injection
            r"\b(DROP|DELETE|INSERT|UPDATE|ALTER|CREATE|EXEC|EXECUTE)\b",
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, value, re.IGNORECASE):
                raise ValueError(f"String contains dangerous pattern: {value}")

        escaped = value.replace("'", "''")

        if not re.match(r"^[a-zA-Z0-9._\-/%\s:,']*$", escaped):
            raise ValueError(f"String contains invalid characters: {value}")

        return escaped

    @staticmethod
    def _validate_crawl_id(crawl_id: str) -> str:
        """Validate and sanitize crawl ID.

        Args:
            crawl_id: Crawl identifier to validate

        Returns:
            Validated crawl ID

        Raises:
            ValueError: If crawl ID is invalid
        """
        if not isinstance(crawl_id, str):
            raise ValueError("Crawl ID must be a string")

        if not re.match(r"^CC-MAIN-\d{4}-\d{2}$", crawl_id):
            raise ValueError(f"Invalid crawl ID format: {crawl_id}")

        return crawl_id

    @staticmethod
    def _validate_integer(value: int, min_val: int = 0, max_val: int = 1000000) -> int:
        """Validate integer values.

        Args:
            value: Integer to validate
            min_val: Minimum allowed value
            max_val: Maximum allowed value

        Returns:
            Validated integer

        Raises:
            ValueError: If integer is out of range
        """
        if not isinstance(value, int):
            raise ValueError(f"Expected integer, got {type(value)}")

        if not min_val <= value <= max_val:
            raise ValueError(f"Integer {value} not in range [{min_val}, {max_val}]")

        return value

    @staticmethod
    def _build_exact_match_condition(column: str, values: List[str]) -> str:
        """Build exact match condition using = or IN based on number of values.

        Args:
            column: Column name
            values: List of string values (already validated/escaped)

        Returns:
            SQL condition string

        Examples:
            >>> _build_exact_match_condition("crawl", ["CC-MAIN-2024-33"])
            "crawl = 'CC-MAIN-2024-33'"
            >>> _build_exact_match_condition("crawl", ["CC-MAIN-2024-33", "CC-MAIN-2024-30"])
            "crawl IN ('CC-MAIN-2024-33','CC-MAIN-2024-30')"
        """
        if len(values) == 1:
            return f"{column} = '{values[0]}'"
        else:
            value_list = "','".join(values)
            return f"{column} IN ('{value_list}')"

    @staticmethod
    def _build_exact_match_condition_int(column: str, values: List[int]) -> str:
        """Build exact match condition for integers using = or IN based on number of values.

        Args:
            column: Column name
            values: List of integer values (already validated)

        Returns:
            SQL condition string

        Examples:
            >>> _build_exact_match_condition_int("fetch_status", [200])
            "fetch_status = 200"
            >>> _build_exact_match_condition_int("fetch_status", [200, 201, 202])
            "fetch_status IN (200,201,202)"
        """
        if len(values) == 1:
            return f"{column} = {values[0]}"
        else:
            value_list = ",".join(map(str, values))
            return f"{column} IN ({value_list})"

    @staticmethod
    def _build_like_conditions(column: str, values: List[str]) -> str:
        """Build LIKE conditions combined with OR.

        Args:
            column: Column name
            values: List of string values (already escaped)

        Returns:
            SQL condition string (wrapped in parentheses if multiple)

        Examples:
            >>> _build_like_conditions("url", ["%.edu%"])
            "url LIKE '%.edu%'"
            >>> _build_like_conditions("url", ["%.edu%", "%.gov%"])
            "(url LIKE '%.edu%' OR url LIKE '%.gov%')"
        """
        conditions = [f"{column} LIKE '{value}'" for value in values]
        if len(conditions) == 1:
            return conditions[0]
        else:
            return f"({' OR '.join(conditions)})"

    def to_sql(self, count_only: bool = False) -> str:
        """Build and return SQL query string with SQL injection protection.

        Args:
            count_only: If True, returns SELECT COUNT(*) query instead of full column list

        Returns:
            Complete SQL query for ccindex table

        Raises:
            ValueError: If any input values are invalid or potentially malicious
        """
        if count_only:
            select_clause = "SELECT COUNT(*)"
        else:
            select_clause = """
            SELECT
                url,
                url_host_name,
                fetch_time,
                fetch_status,
                content_mime_type,
                content_charset,
                content_languages,
                warc_filename,
                warc_record_offset,
                warc_record_length
            """

        # Handle crawl IDs (multiple or single), default to latest if not specified
        if self.filter_config.crawl_ids:
            validated_crawls = [
                self._validate_crawl_id(cid) for cid in self.filter_config.crawl_ids
            ]
        else:
            # Default to latest crawl if not specified
            validated_crawls = [self._validate_crawl_id("CC-MAIN-2024-33")]

        where_conditions = [
            self._build_exact_match_condition("crawl", validated_crawls),
            "subset = 'warc'",
        ]

        if self.filter_config.url_patterns:
            safe_patterns = [
                self._escape_sql_string(pattern.replace("*", "%"))
                for pattern in self.filter_config.url_patterns
            ]
            where_conditions.append(self._build_like_conditions("url", safe_patterns))

        if self.filter_config.url_host_names:
            safe_hosts = [
                self._escape_sql_string(hostname)
                for hostname in self.filter_config.url_host_names
            ]
            where_conditions.append(
                self._build_exact_match_condition("url_host_name", safe_hosts)
            )

        if self.filter_config.url_host_tlds:
            safe_tlds = [
                self._escape_sql_string(tld)
                for tld in self.filter_config.url_host_tlds
            ]
            where_conditions.append(
                self._build_exact_match_condition("url_host_tld", safe_tlds)
            )

        if self.filter_config.url_host_registered_domains:
            safe_domains = [
                self._escape_sql_string(domain)
                for domain in self.filter_config.url_host_registered_domains
            ]
            where_conditions.append(
                self._build_exact_match_condition("url_host_registered_domain", safe_domains)
            )

        if self.filter_config.url_paths:
            safe_paths = [
                self._escape_sql_string(path)
                for path in self.filter_config.url_paths
            ]
            where_conditions.append(
                self._build_like_conditions("url_path", safe_paths)
            )

        if self.filter_config.status_codes:
            validated_codes = [
                self._validate_integer(code, 100, 599)
                for code in self.filter_config.status_codes
            ]
            where_conditions.append(
                self._build_exact_match_condition_int("fetch_status", validated_codes)
            )

        if self.filter_config.mime_types:
            safe_mimes = [
                self._escape_sql_string(mime_type) + "%"
                for mime_type in self.filter_config.mime_types
            ]
            where_conditions.append(
                self._build_like_conditions("content_mime_type", safe_mimes)
            )

        if self.filter_config.languages:
            safe_langs = [
                "%" + self._escape_sql_string(language) + "%"
                for language in self.filter_config.languages
            ]
            where_conditions.append(
                self._build_like_conditions("content_languages", safe_langs)
            )

        if self.filter_config.charsets:
            safe_charsets = [
                self._escape_sql_string(charset) + "%"
                for charset in self.filter_config.charsets
            ]
            where_conditions.append(
                self._build_like_conditions("content_charset", safe_charsets)
            )

        if self.filter_config.date_from:
            safe_date_from = self._escape_sql_string(self.filter_config.date_from)
            where_conditions.append(f"fetch_time >= '{safe_date_from}'")

        if self.filter_config.date_to:
            safe_date_to = self._escape_sql_string(self.filter_config.date_to)
            where_conditions.append(f"fetch_time <= '{safe_date_to}'")

        if self.filter_config.custom_filters:
            for custom_filter in self.filter_config.custom_filters:
                safe_custom = self._validate_custom_filter(custom_filter)
                where_conditions.append(f"({safe_custom})")

        query = f"""
        {select_clause}
        FROM {self.database}.{self.table}
        WHERE {" AND ".join(where_conditions)}
        """

        if self.limit and not count_only:
            safe_limit = self._validate_integer(self.limit, 1, 100000)
            query += f" LIMIT {safe_limit}"

        return query.strip()

    def _validate_custom_filter(self, custom_filter: str) -> str:
        """Validate custom filter to prevent SQL injection.

        Args:
            custom_filter: Custom SQL WHERE condition

        Returns:
            Validated custom filter

        Raises:
            ValueError: If custom filter contains dangerous patterns
        """
        if not isinstance(custom_filter, str):
            raise ValueError("Custom filter must be a string")

        dangerous_patterns = [
            r"\b(DROP|DELETE|INSERT|UPDATE|ALTER|CREATE|EXEC|EXECUTE)\b",
            r";",  # Statement separators
            r"--",  # SQL comments
            r"/\*",  # Block comments
            r"\*/",  # Block comments
            r"xp_",  # Extended stored procedures
            r"sp_",  # System stored procedures
            r"UNION\s+SELECT",  # Union injection
            r"@@",  # System variables
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, custom_filter, re.IGNORECASE):
                raise ValueError(
                    f"Custom filter contains dangerous pattern: {custom_filter}"
                )

        if not re.match(
            r'^[a-zA-Z_][a-zA-Z0-9_]*\s*(=|!=|<|>|<=|>=|LIKE|IN)\s*[\'"]?[a-zA-Z0-9._\-/%\s,()]+[\'"]?$',
            custom_filter.strip(),
        ):
            raise ValueError(f"Custom filter format is invalid: {custom_filter}")

        return custom_filter.strip()


class CCAthenaClient:
    """Simple AWS Athena client for querying Common Crawl data.

    Takes AthenaSettings from config.py and creates a boto3 athena client.
    """

    def __init__(self, settings: AthenaSettings):
        """Initialize Athena client with settings.

        Args:
            settings: AthenaSettings instance from config.py

        Raises:
            ValueError: If settings are invalid
            NoCredentialsError: If AWS credentials are not configured
            AthenaQueryError: If Athena setup fails
        """
        if not settings.is_configured():
            raise ValueError(
                "AthenaSettings not properly configured - output_bucket is required"
            )

        self.settings = settings

        try:
            self.athena_client = boto3.client(
                "athena", region_name=settings.region_name
            )
            self.s3_client = boto3.client("s3", region_name=settings.region_name)

            self.athena_client.list_work_groups()

            logger.info(f"CCAthenaClient initialized for region {settings.region_name}")

        except NoCredentialsError:
            raise NoCredentialsError(
                "AWS credentials not found. Please configure AWS credentials using "
                "AWS CLI, environment variables, or IAM roles."
            )
        except (BotoCoreError, Exception) as e:
            raise AthenaQueryError(f"Failed to initialize Athena client: {e}")

    def search(
        self,
        url_pattern: str,
        limit: Optional[int] = None,
        crawl: str = "CC-MAIN-2024-33",
    ) -> List[CrawlRecord]:
        """Search Common Crawl data using Athena.

        Args:
            url_pattern: URL pattern to search (supports SQL LIKE patterns with %)
            limit: Maximum number of results (uses settings.max_results if None)
            crawl: Specific crawl to search (e.g., "CC-MAIN-2024-33")

        Returns:
            List of CrawlRecord objects

        Raises:
            AthenaQueryError: If query fails
        """
        filter_config = FilterConfig(url_patterns=[url_pattern])
        return self.search_with_filter(filter_config, limit, crawl)

    def search_with_filter(
        self,
        filter_config: FilterConfig,
        limit: Optional[int] = None,
    ) -> List[CrawlRecord]:
        """Search Common Crawl data using FilterConfig.

        Args:
            filter_config: FilterConfig with search criteria (including crawl_ids)
            limit: Maximum number of results (uses settings.max_results if None)

        Returns:
            List of CrawlRecord objects

        Raises:
            AthenaQueryError: If query fails
        """
        if limit is None:
            limit = self.settings.max_results

        query_builder = CrawlQueryBuilder(filter_config, limit)
        query = query_builder.to_sql()

        logger.info(f"Searching Common Crawl with filter: {filter_config.url_patterns}")
        logger.debug(f"Athena query: {query}")

        try:
            query_execution_id = self._execute_query(query)
            results = self._get_query_results(query_execution_id)

            records = []
            for row in results:
                record = self._row_to_crawl_record(row)
                if record:
                    records.append(record)

            logger.info(f"Retrieved {len(records)} records from Athena")
            return records

        except Exception as e:
            raise AthenaQueryError(f"Athena search failed: {e}")

    def list_crawls(self) -> List[str]:
        """List available crawls from Common Crawl index.

        Returns:
            List of crawl IDs sorted in descending order (newest first)

        Raises:
            AthenaQueryError: If query fails
        """
        query = """
        SELECT DISTINCT crawl
        FROM ccindex.ccindex
        WHERE subset = 'warc'
        ORDER BY crawl DESC
        """

        logger.info("Listing available crawls from Common Crawl")
        logger.debug(f"Athena query: {query}")

        try:
            query_execution_id = self._execute_query(query)
            results = self._get_query_results(query_execution_id)

            crawls = [row[0] for row in results if row and row[0]]

            logger.info(f"Found {len(crawls)} available crawls")
            return crawls

        except Exception as e:
            raise AthenaQueryError(f"Failed to list crawls: {e}")

    def _execute_query(self, query: str) -> str:
        """Execute Athena query and return execution ID."""
        logger.info(f"Executing Athena query: {query}")
        response = self.athena_client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": "ccindex"},
            ResultConfiguration={"OutputLocation": self.settings.output_location},
            WorkGroup="primary",
        )

        query_execution_id = response["QueryExecutionId"]
        self._wait_for_completion(query_execution_id)
        return query_execution_id

    def _wait_for_completion(self, query_execution_id: str) -> None:
        """Wait for Athena query to complete."""
        import time

        start_time = time.time()

        while True:
            response = self.athena_client.get_query_execution(
                QueryExecutionId=query_execution_id
            )

            status = response["QueryExecution"]["Status"]["State"]

            if status == "SUCCEEDED":
                logger.info(f"{query_execution_id} Query completed successfully")
                return
            elif status in ["FAILED", "CANCELLED"]:
                reason = response["QueryExecution"]["Status"].get(
                    "StateChangeReason", "Unknown error"
                )
                logger.warning(f"{query_execution_id} Query failed: {reason}")
                raise AthenaQueryError(f"Query failed: {reason}")
            elif status in ["QUEUED", "RUNNING"]:
                elapsed = time.time() - start_time
                if elapsed > self.settings.timeout_seconds:
                    self.athena_client.stop_query_execution(
                        QueryExecutionId=query_execution_id
                    )
                    logger.warning(
                        f"{query_execution_id} Query timed out after {self.settings.timeout_seconds} seconds"
                    )
                    raise AthenaQueryError(
                        f"Query timed out after {self.settings.timeout_seconds} seconds"
                    )

                time.sleep(2)  # Wait before checking again
            else:
                logger.warning(f"{query_execution_id} Unknown query status: {status}")
                raise AthenaQueryError(f"Unknown query status: {status}")

    def _get_query_results(self, query_execution_id: str) -> List[List[str]]:
        """Get results from completed Athena query."""
        results = []
        paginator = self.athena_client.get_paginator("get_query_results")

        for page in paginator.paginate(
            QueryExecutionId=query_execution_id,
            PaginationConfig={"MaxItems": self.settings.max_results},
        ):
            for i, row in enumerate(page["ResultSet"]["Rows"]):
                if i == 0:
                    continue

                row_data = []
                for data in row["Data"]:
                    value = data.get("VarCharValue", "")
                    row_data.append(value)

                results.append(row_data)

        return results

    def _row_to_crawl_record(self, row: List[str]) -> Optional[CrawlRecord]:
        """Convert Athena result row to CrawlRecord."""
        try:
            if len(row) < 10:
                return None

            url = row[0]
            fetch_time = row[2] if row[2] else ""
            fetch_status = int(row[3]) if row[3] and row[3].isdigit() else 0
            mime_type = row[4] if row[4] else ""
            charset = row[5] if row[5] else ""
            languages_str = row[6] if row[6] else ""
            filename = row[7] if row[7] else ""
            offset = int(row[8]) if row[8] and row[8].isdigit() else 0
            length = int(row[9]) if row[9] and row[9].isdigit() else 0

            languages = []
            if languages_str:
                languages = [lang.strip() for lang in languages_str.split(",")]

            timestamp = ""
            if fetch_time and " " in fetch_time:
                timestamp = fetch_time.split(" ")[0].replace("-", "")

            return CrawlRecord(
                urlkey=url.replace("https://", "").replace("http://", ""),
                timestamp=timestamp,
                url=url,
                mime=mime_type,
                status=fetch_status,
                digest="",  # Not available from Athena
                length=length,
                offset=offset,
                filename=filename,
                charset=charset,
                languages=languages,
            )

        except (ValueError, IndexError) as e:
            logger.warning(f"Failed to convert row to CrawlRecord: {e}")
            return None
