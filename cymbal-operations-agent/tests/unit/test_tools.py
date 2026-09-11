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

"""Unit tests for Cymbal Operations Agent tools."""

import unittest
from app.tools.rag_tool import pos_troubleshooting_rag_tool
from app.tools.bigtable_tool import _parse_mcp_bigtable_response


class TestAgentTools(unittest.TestCase):
    """Unit tests for RAG guardrails and Bigtable parsing."""

    def test_rag_tool_out_of_scope_guardrail(self):
        """Verify that out-of-scope queries return the certified declining string."""
        out_of_scope_query = "How do I replace the engine oil on a Ford F-150 truck?"
        result = pos_troubleshooting_rag_tool(out_of_scope_query)
        expected_declining = "I cannot find certified warranty or repair rules for this specific error in our technical repository."
        self.assertIn(expected_declining, result)

    def test_rag_tool_in_scope_hardware_diagnostic(self):
        """Verify that in-scope POS hardware error returns recovery instructions."""
        in_scope_query = "What is the immediate field recovery protocol for ERR-PAY-4001 EMV contactless payment freeze?"
        result = pos_troubleshooting_rag_tool(in_scope_query)
        self.assertTrue("ERR-PAY-4001" in result or "payment" in result.lower())
        self.assertTrue(any(term in result.lower() for term in ["reboot", "lane", "terminal", "recovery", "power"]))

    def test_bigtable_mcp_response_parser(self):
        """Test parsing empty or invalid MCP tool responses gracefully."""
        self.assertIsNone(_parse_mcp_bigtable_response({}, "STORE_048#CASH_1190"))
        self.assertIsNone(_parse_mcp_bigtable_response({"content": []}, "STORE_048#CASH_1190"))
        self.assertIsNone(_parse_mcp_bigtable_response({"content": [{"type": "text", "text": "invalid json"}]}, "STORE_048#CASH_1190"))


if __name__ == "__main__":
    unittest.main()
