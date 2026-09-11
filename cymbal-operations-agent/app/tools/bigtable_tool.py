"""Cloud Bigtable MCP Toolset connecting to Cloud Run microservice with OIDC authentication and direct SDK fallback."""

import base64
import json
import logging
import os
import re
import struct
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT", "")
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
        content_text = content_items[0].get("text", "{}")
        parsed_data = json.loads(content_text)
        if isinstance(parsed_data, list):
            if not parsed_data:
                return f"No real-time records found in Bigtable for prefix '{prefix}'."
            row = parsed_data[0]
        elif isinstance(parsed_data, dict):
            row = parsed_data
        else:
            return f"No real-time records found in Bigtable for prefix '{prefix}'."
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


def _parse_mcp_pos_transactions(mcp_resp: dict) -> Optional[str]:
    """Parses base64-encoded Database Toolbox response for pos_transactions_enriched."""
    try:
        content_list = mcp_resp.get("content", [])
        if not content_list:
            result_obj = mcp_resp.get("result", {})
            content_list = result_obj.get("content", [])
        if not content_list:
            return None

        transactions = []
        for item in content_list:
            text_val = item.get("text", "")
            if not text_val:
                continue
            row_data = json.loads(text_val)
            tx_family = row_data.get("tx", {})
            decoded_tx = {}
            for k_b64, v_b64 in tx_family.items():
                k = base64.b64decode(k_b64).decode("utf-8")
                val_bytes = base64.b64decode(v_b64)
                try:
                    v = val_bytes.decode("utf-8")
                except Exception:
                    v = str(val_bytes)
                decoded_tx[k] = v
            if decoded_tx:
                transactions.append(decoded_tx)

        if not transactions:
            return None

        headers = ["Txn ID", "Timestamp", "Store", "POS Terminal", "Cashier ID", "Total", "Payment Method", "Card Brand"]
        rows = []
        for t in transactions[:10]:
            try:
                tot_float = float(t.get("total", 0))
                tot_str = f"${tot_float:.2f}"
            except (ValueError, TypeError):
                tot_str = str(t.get("total", "$0.00"))

            ts_str = str(t.get("event_timestamp", "N/A"))[:19]
            pay_method = str(t.get("payment_method", "N/A"))
            card_brand = t.get("card_brand") or t.get("payment_network", "N/A")
            raw_pan = str(t.get("card_number") or t.get("pan", ""))
            if raw_pan:
                clean_digits = re.sub(r"\D", "", raw_pan)
                last4 = clean_digits[-4:] if len(clean_digits) >= 4 else "XXXX"
                brand_str = f"{card_brand} (****-****-****-{last4})"
            else:
                brand_str = str(card_brand)

            rows.append([
                t.get("transaction_id", "N/A"),
                ts_str,
                str(t.get("store_id", "N/A")),
                str(t.get("pos_terminal_id", "N/A")),
                str(t.get("cashier_id", "N/A")),
                tot_str,
                pay_method,
                brand_str
            ])

        header_line = "| " + " | ".join(headers) + " |"
        sep_line = "| " + " | ".join("---" for _ in headers) + " |"
        data_lines = ["| " + " | ".join(r) + " |" for r in rows]
        table = "\n".join([header_line, sep_line] + data_lines)

        return (
            f"### Enriched Real-Time POS Transactions (Bigtable)\n\n"
            f"{table}\n\n"
            f"*(Retrieved {len(transactions)} enriched checkout logs via Cloud Run Database Toolbox)*"
        )
    except Exception as e:
        logger.warning(f"Failed to parse enriched transactions: {e}")
        return None


def read_pos_transactions_enriched(store_id: int, pos_terminal_id: str = "") -> str:
    """Reads enriched real-time POS transaction logs from Cloud Bigtable for a store register with partition pruning.

    Args:
        store_id: The integer store identifier (e.g., 48 or '48').
        pos_terminal_id: Optional register ID (e.g., 'POS_01' or '01'). If omitted, queries all registers at the store.
    Returns:
        Structured markdown table of recent enriched checkout transactions with line items, payment types, and audit flags.
    """
    try:
        store_num = int(re.sub(r"[^\d]", "", str(store_id)))
    except ValueError:
        store_num = 0

    prefix = f"STORE_{store_num:03d}"
    clean_pos = str(pos_terminal_id).strip().upper()
    if clean_pos:
        if not clean_pos.startswith("POS_"):
            clean_pos = f"POS_{clean_pos}"
        prefix = f"{prefix}#{clean_pos}"

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
                    "name": "read_pos_transactions_enriched_sql",
                    "arguments": {"key_prefix": prefix}
                }
            }
            resp = requests.post(f"{mcp_url}/mcp", json=payload, headers=headers, timeout=10)
            if resp.status_code == 200:
                parsed = _parse_mcp_pos_transactions(resp.json())
                if parsed:
                    return parsed
        except Exception as e:
            logger.warning(f"MCP read_pos_transactions failed: {e}")

    return f"No recent enriched POS transactions found for prefix `{prefix}` in Bigtable."


read_pos_transactions_tool = read_pos_transactions_enriched

