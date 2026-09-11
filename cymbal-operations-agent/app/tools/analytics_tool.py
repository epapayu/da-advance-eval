"""Analytics Tool wrapping BigQuery Conversational Data Agent API."""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DATA_AGENT_RESOURCE = os.getenv(
    "DATA_AGENT_RESOURCE_NAME",
    "projects/praxis-magnet-508004-d7/locations/global/dataAgents/gda-f0056a5c-197e-411e-9454-9da119bbf1c0"
)
DATA_AGENT_LOCATION = os.getenv("DATA_AGENT_LOCATION", "global")


def _get_credentials():
    import google.auth
    import google.auth.transport.requests
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    return creds


def _format_data_table(headers: List[str], rows: List[List[Any]], max_rows: int = 15) -> str:
    """Formats retrieved data into a clean GitHub Flavored Markdown table."""
    if not headers or not rows:
        return ""
    
    header_line = "| " + " | ".join(str(h) for h in headers) + " |"
    sep_line = "| " + " | ".join("---" for _ in headers) + " |"
    data_lines = []
    for r in rows[:max_rows]:
        data_lines.append("| " + " | ".join(str(val) for val in r) + " |")
    
    table_str = "\n".join([header_line, sep_line] + data_lines)
    if len(rows) > max_rows:
        table_str += f"\n*(Showing top {max_rows} of {len(rows)} rows)*"
    return table_str


def _format_agent_response(resp_dict: Dict[str, Any]) -> str:
    """Parses raw ask_data_agent response into rich formatted Markdown."""
    if resp_dict.get("status") == "ERROR":
        return f"Data Agent Error: {resp_dict.get('error_details', 'Unknown error')}"

    response_steps = resp_dict.get("response", [])
    if not response_steps:
        return "No data returned from the Data Agent."

    final_text_parts = []
    generated_sql = None
    data_table = ""

    for step in response_steps:
        if "text" in step:
            t_obj = step["text"]
            if t_obj.get("textType") == "FINAL_RESPONSE":
                final_text_parts.extend(t_obj.get("parts", []))
        if "data" in step:
            d_obj = step["data"]
            if "generatedSql" in d_obj:
                generated_sql = d_obj["generatedSql"]
            elif "matchedQuery" in d_obj:
                generated_sql = d_obj["matchedQuery"].get("exampleQuery", {}).get("sqlQuery")
        if "Data Retrieved" in step:
            dr = step["Data Retrieved"]
            headers = dr.get("headers", [])
            rows = dr.get("rows", [])
            data_table = _format_data_table(headers, rows)

    out = []
    if final_text_parts:
        out.append("\n\n".join(final_text_parts))
    if data_table:
        out.append("\n### Query Results\n" + data_table)
    if generated_sql:
        out.append(f"\n```sql\n-- Generated GoogleSQL\n{generated_sql.strip()}\n```")

    if not out:
        return str(response_steps)

    return "\n\n".join(out)


def _call_data_agent_with_retry(query: str, max_retries: int = 3) -> str:
    """Invokes ask_data_agent with exponential backoff retries."""
    import google.adk.tools.data_agent.data_agent_tool as data_agent_tool
    from google.adk.tools.data_agent.config import DataAgentToolConfig

    if DATA_AGENT_LOCATION != "global":
        data_agent_tool.BASE_URL = (
            f"https://geminidataanalytics.{DATA_AGENT_LOCATION}.rep.googleapis.com/v1beta"
        )

    config = DataAgentToolConfig()
    delay = 2.0
    last_err = None

    for attempt in range(1, max_retries + 1):
        try:
            creds = _get_credentials()
            raw_res = data_agent_tool.ask_data_agent(
                data_agent_name=DATA_AGENT_RESOURCE,
                query=query,
                credentials=creds,
                settings=config,
                tool_context=None
            )
            return _format_agent_response(raw_res)
        except Exception as e:
            last_err = e
            logger.warning(
                f"[Attempt {attempt}/{max_retries}] Data Agent invocation failed: {e}. Retrying in {delay}s..."
            )
            time.sleep(delay)
            delay *= 2.0

    raise last_err


def cymbal_analytics_tool(user_query: str) -> str:
    """Queries conformed enterprise retail analytics in Google Cloud BigQuery and federated AWS S3.

    Use this tool for:
    - Today's intraday sales transactions, net revenue, and units sold.
    - Store inventory levels, on-hand counts, and stockout risk (<20 hours cover).
    - Customer historical purchase records and warranty eligibility lookups.
    - Multi-day cashier promo abuse and anomaly alert rankings (GCP).
    - Cross-cloud transaction log auditing in federated AWS S3.

    Args:
        user_query: The natural language question. Standard business glossary terms 
                    (e.g., 'Net Transaction Revenue', 'Total On-Hand Inventory', 
                    'Estimated Cover Hours', 'Cashier Promo Override Rate') 
                    must be preserved verbatim.
    Returns:
        Structured relational query findings, data tables, and analysis from the BigQuery Data Agent.
    """
    try:
        logger.info(f"Dispatching query to BigQuery Data Agent: {user_query}")
        result = _call_data_agent_with_retry(user_query)
        if not result or not str(result).strip():
            return "No matching records found in the retail analytics ledger."
        return str(result)
    except Exception as e:
        logger.error(f"Failed to query Data Agent: {e}", exc_info=True)
        return (
            "Store data is currently unreachable due to a temporary network or service disruption. "
            "Please verify database connectivity or retry in a few moments."
        )


query_retail_analytics = cymbal_analytics_tool
