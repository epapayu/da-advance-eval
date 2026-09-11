# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Isolated Unit tests for Cymbal Operations Agent tools using mocks."""

import base64
import json
import unittest
from unittest.mock import MagicMock, patch

from app.tools.analytics_tool import cymbal_analytics_tool
from app.tools.bigtable_tool import (
    _parse_mcp_bigtable_response,
    _parse_mcp_pos_transactions,
    read_pos_transactions_enriched,
)
from app.tools.rag_tool import pos_troubleshooting_rag_tool


class TestAgentToolsMocked(unittest.TestCase):
    """Unit tests verifying tool logic with isolated mocks (no live GCP network calls)."""

    @patch("app.tools.rag_tool._run_stitched_vector_search")
    def test_rag_tool_out_of_scope_guardrail(self, mock_search):
        """Verify that out-of-scope queries return the certified declining string immediately."""
        mock_search.return_value = []
        out_of_scope_query = "How do I replace the engine oil on a Ford F-150 truck?"
        result = pos_troubleshooting_rag_tool(out_of_scope_query)
        expected_declining = "I cannot find certified warranty or repair rules for this specific error in our technical repository."
        self.assertIn(expected_declining, result)

    @patch("app.tools.rag_tool._run_stitched_vector_search")
    def test_rag_tool_in_scope_hardware_diagnostic(self, mock_search):
        """Verify in-scope POS error with mocked BigQuery vector response."""
        mock_row = MagicMock()
        mock_row.document_title = "Toshiba TCx 810 Guide"
        mock_row.equipment_covered = "Toshiba TCx 810 POS Terminal"
        mock_row.source_pdf_uri = "gs://cymbal-bucket/Toshiba_TCx_810_Guide.pdf"
        mock_row.similarity_score = 0.95
        mock_row.full_runbook = "ERR-PAY-4001: Reboot terminal and cancel hung tokenization lock."
        mock_search.return_value = [mock_row]

        in_scope_query = "What is the recovery protocol for ERR-PAY-4001 payment freeze?"
        result = pos_troubleshooting_rag_tool(in_scope_query)

        self.assertIn("Toshiba TCx 810", result)
        self.assertIn("https://storage.cloud.google.com/cymbal-bucket/Toshiba_TCx_810_Guide.pdf", result)
        self.assertIn("Reboot terminal", result)

    def test_bigtable_mcp_response_parser(self):
        """Test parsing empty or invalid MCP tool responses gracefully."""
        self.assertIsNone(_parse_mcp_bigtable_response({}, "STORE_048#CASH_1190"))
        self.assertIsNone(_parse_mcp_bigtable_response({"content": []}, "STORE_048#CASH_1190"))
        self.assertIsNone(_parse_mcp_bigtable_response({"content": [{"type": "text", "text": "invalid json"}]}, "STORE_048#CASH_1190"))

    def test_pos_transactions_parser(self):
        """Test parsing mock Database Toolbox response for enriched POS transactions."""
        # Construct sample row with base64 encoded strings
        sample_row = {
            "_key": base64.b64encode(b"STORE_048#TXN-001").decode("utf-8"),
            "tx": {
                base64.b64encode(b"transaction_id").decode("utf-8"): base64.b64encode(b"TXN-001").decode("utf-8"),
                base64.b64encode(b"event_timestamp").decode("utf-8"): base64.b64encode(b"2026-09-11 02:00:00").decode("utf-8"),
                base64.b64encode(b"store_id").decode("utf-8"): base64.b64encode(b"STORE_048").decode("utf-8"),
                base64.b64encode(b"pos_terminal_id").decode("utf-8"): base64.b64encode(b"POS_01").decode("utf-8"),
                base64.b64encode(b"cashier_id").decode("utf-8"): base64.b64encode(b"CASH_1190").decode("utf-8"),
                base64.b64encode(b"total").decode("utf-8"): base64.b64encode(b"42.50").decode("utf-8"),
                base64.b64encode(b"payment_method").decode("utf-8"): base64.b64encode(b"CREDIT_CARD").decode("utf-8"),
                base64.b64encode(b"payment_network").decode("utf-8"): base64.b64encode(b"VISA").decode("utf-8"),
            }
        }
        mock_mcp_resp = {
            "result": {
                "content": [{"type": "text", "text": json.dumps(sample_row)}]
            }
        }
        parsed_table = _parse_mcp_pos_transactions(mock_mcp_resp)
        self.assertIsNotNone(parsed_table)
        self.assertIn("TXN-001", parsed_table)
        self.assertIn("$42.50", parsed_table)
        self.assertIn("CREDIT_CARD", parsed_table)
        self.assertIn("VISA", parsed_table)
        self.assertIn("POS_01", parsed_table)

    @patch("app.tools.analytics_tool._call_data_agent_with_retry")
    def test_analytics_tool_unreachable_exception(self, mock_api):
        """Verify that connectivity exceptions return structured JSON with UNREACHABLE status."""
        mock_api.side_effect = ConnectionError("Failed to connect to BigQuery Data Agent backend")
        result_str = cymbal_analytics_tool("What is the total revenue?")
        
        parsed = json.loads(result_str)
        self.assertEqual(parsed.get("status"), "UNREACHABLE")
        self.assertIn("Store data is currently unreachable", parsed.get("message", ""))

    @patch("app.tools.analytics_tool._call_data_agent_with_retry")
    def test_analytics_tool_success(self, mock_api):
        """Verify successful analytics query formatting."""
        mock_api.return_value = "| Store | Cover Hours |\n| --- | --- |\n| STORE_001 | 18.5 |"
        result_str = cymbal_analytics_tool("What are store inventory cover hours?")
        self.assertIn("STORE_001", result_str)
        self.assertIn("18.5", result_str)


if __name__ == "__main__":
    unittest.main()
