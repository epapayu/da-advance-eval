"""Cloud Bigtable MCP Toolset connecting to Cloud Run microservice with OIDC authentication and direct SDK fallback."""

import logging
import os
import re
import struct
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "praxis-magnet-508004-d7")
BIGTABLE_INSTANCE_ID = os.getenv("BIGTABLE_INSTANCE_ID", "operations-db")
BIGTABLE_TABLE_ID = os.getenv("BIGTABLE_TABLE_ID", "cashier_realtime_alerts")
MCP_SERVICE_URL = os.getenv("BIGTABLE_MCP_URL", "")


def _get_oidc_token(audience: str) -> Optional[str]:
    """Generates GCP OIDC ID token for authenticated Cloud Run service."""
    try:
        import google.auth
        import google.auth.transport.requests
        from google.oauth2 import id_token
        auth_req = google.auth.transport.requests.Request()
        return id_token.fetch_id_token(auth_req, audience)
    except Exception as e:
        logger.warning(f"Could not generate OIDC token: {e}")
        return None


def _decode_bigtable_cell(col_name: str, val: bytes):
    """Deserializes Bigtable cell bytes into appropriate Python types."""
    if len(val) == 8:
        lower = col_name.lower()
        if lower.endswith("_count") or "txn_count" in lower:
            try:
                return struct.unpack(">q", val)[0]
            except Exception:
                pass
        if any(term in lower for term in ["rate", "pct", "usd", "score"]):
            try:
                return round(struct.unpack(">d", val)[0], 4)
            except Exception:
                pass
    try:
        return val.decode("utf-8")
    except Exception:
        return str(val)


def _fallback_direct_bigtable_read(prefix: str) -> str:
    """Direct Bigtable SDK read matching prefix to get latest rolling metrics."""
    try:
        from google.cloud import bigtable
        from google.cloud.bigtable.row_set import RowSet

        client = bigtable.Client(project=PROJECT_ID, admin=False)
        instance = client.instance(BIGTABLE_INSTANCE_ID)
        table = instance.table(BIGTABLE_TABLE_ID)

        row_set = RowSet()
        row_set.add_row_range_with_prefix(prefix)
        rows = list(table.read_rows(row_set=row_set, limit=1))

        if not rows:
            return (
                f"No real-time records found in Bigtable instance '{BIGTABLE_INSTANCE_ID}' "
                f"for prefix '{prefix}'."
            )

        row = rows[0]
        parsed = {
            "row_key": row.row_key.decode("utf-8"),
            "metrics": {}
        }
        for col_family, cols in row.cells.items():
            for col_name, cell_list in cols.items():
                name_str = col_name.decode("utf-8")
                parsed["metrics"][name_str] = _decode_bigtable_cell(name_str, cell_list[0].value)

        metrics = parsed["metrics"]
        override_rate = metrics.get("cashier_1h_promo_rate", 0.0)
        override_count = metrics.get("cashier_1h_manual_override_count", 0)
        txn_count = metrics.get("cashier_1h_txn_count", 0)
        audit_status = metrics.get("audit_status", "UNKNOWN")
        total_discount = metrics.get("cashier_1h_total_discount_usd", 0.0)
        last_ts = metrics.get("last_event_ts", "N/A")

        return (
            f"### Real-Time Cashier Metrics (Bigtable: `{parsed['row_key']}`)\n"
            f"- **Audit Status Flag:** `{audit_status}`\n"
            f"- **Live 1-Hour Override / Promo Rate:** `{override_rate * 100:.2f}%` ({override_rate})\n"
            f"- **Live 1-Hour Manual Overrides:** `{override_count}` / `{txn_count}` transactions\n"
            f"- **Live 1-Hour Discount Total:** `${total_discount:.2f} USD`\n"
            f"- **Last Event Timestamp:** `{last_ts}`\n"
            f"\nFull Telemetry Payload:\n"
            f"```json\n"
            f"{metrics}\n"
            f"```\n"
        )
    except Exception as e:
        logger.error(f"Direct Bigtable read failed: {e}", exc_info=True)
        return (
            f"Real-time cashier alert cache is currently unavailable. "
            f"Details: {e}"
        )


import base64
import json


def _parse_mcp_bigtable_response(resp_data: dict, prefix: str) -> Optional[str]:
    """Parses and formats JSON-RPC response from the Cloud Run Bigtable MCP service."""
    try:
        content_items = resp_data.get("result", {}).get("content", [])
        if not content_items:
            return None
        content_text = content_items[0].get("text", "[]")
        rows = json.loads(content_text)
        if not rows:
            return f"No real-time records found in Bigtable for prefix '{prefix}'."

        row = rows[0]
        row_key_raw = row.get("_key", "")
        if row_key_raw:
            try:
                row_key = base64.b64decode(row_key_raw).decode("utf-8", errors="replace")
            except Exception:
                row_key = str(row_key_raw)
        else:
            row_key = prefix

        metrics = {}
        for family in ["flags", "stats"]:
            fam_dict = row.get(family, {})
            if isinstance(fam_dict, dict):
                for k_b64, v_b64 in fam_dict.items():
                    try:
                        col_name = base64.b64decode(k_b64).decode("utf-8", errors="replace")
                    except Exception:
                        col_name = str(k_b64)
                    try:
                        val_bytes = base64.b64decode(v_b64)
                        metrics[col_name] = _decode_bigtable_cell(col_name, val_bytes)
                    except Exception:
                        metrics[col_name] = str(v_b64)

        override_rate = metrics.get("cashier_1h_promo_rate", 0.0)
        override_count = metrics.get("cashier_1h_manual_override_count", 0)
        txn_count = metrics.get("cashier_1h_txn_count", 0)
        audit_status = metrics.get("audit_status", "UNKNOWN")
        total_discount = metrics.get("cashier_1h_total_discount_usd", 0.0)
        last_ts = metrics.get("last_event_ts", "N/A")

        return (
            f"### Real-Time Cashier Metrics (Bigtable: `{row_key}`)\n"
            f"- **Audit Status Flag:** `{audit_status}`\n"
            f"- **Live 1-Hour Override / Promo Rate:** `{override_rate * 100:.2f}%` ({override_rate})\n"
            f"- **Live 1-Hour Manual Overrides:** `{override_count}` / `{txn_count}` transactions\n"
            f"- **Live 1-Hour Discount Total:** `${total_discount:.2f} USD`\n"
            f"- **Last Event Timestamp:** `{last_ts}`\n"
            f"\nFull Telemetry Payload:\n"
            f"```json\n"
            f"{metrics}\n"
            f"```\n"
        )
    except Exception as e:
        logger.warning(f"Error parsing MCP response: {e}")
        return None


def bigtable_mcp_toolset(store_id: int, cashier_id: str) -> str:
    """Queries Cloud Bigtable for real-time 1-hour rolling metrics and status flags for a cashier.

    Args:
        store_id: The integer store identifier (e.g., 48 or '48').
        cashier_id: The cashier ID (e.g., 'CASH_1190' or '1190').
    Returns:
        Structured live metrics including 1-hour override rate, scan voids, and alert flags.
    """
    try:
        store_num = int(re.sub(r"[^\d]", "", str(store_id)))
    except ValueError:
        store_num = 0

    clean_cashier = str(cashier_id).strip()
    if not clean_cashier.startswith("CASH_"):
        clean_cashier = f"CASH_{clean_cashier}"

    prefix = f"STORE_{store_num:03d}#{clean_cashier}"
    mcp_url = os.getenv("BIGTABLE_MCP_URL", MCP_SERVICE_URL).strip()

    if mcp_url:
        try:
            import requests
            token = _get_oidc_token(mcp_url)
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "read_cashier_realtime_alerts_sql",
                    "arguments": {"key_prefix": prefix}
                }
            }
            resp = requests.post(f"{mcp_url}/mcp", json=payload, headers=headers, timeout=10)
            if resp.status_code == 200:
                parsed = _parse_mcp_bigtable_response(resp.json(), prefix)
                if parsed:
                    return parsed
            logger.warning(f"Cloud Run MCP returned status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.warning(f"MCP invocation failed: {e}. Executing direct Bigtable read.")

    return _fallback_direct_bigtable_read(prefix)


query_bigtable_cashier_metrics = bigtable_mcp_toolset
bigtable_mcp_tool = bigtable_mcp_toolset
