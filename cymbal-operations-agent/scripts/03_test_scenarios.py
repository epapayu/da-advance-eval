"""Operational Test Scenarios Runner for Cymbal Retail Operations Agent."""

import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SCENARIOS = [
    {
        "id": "UC 1.1a",
        "category": "Hardware Error",
        "prompt": "What is the immediate field recovery protocol when a cashier encounters an ERR-PAY-4001 EMV contactless payment freeze, and how do we ensure the customer is not double-charged?",
        "expected_tool": "pos_troubleshooting_rag_tool"
    },
    {
        "id": "UC 1.1c",
        "category": "Out-of-Scope Hardware",
        "prompt": "How do I replace the engine oil on a Ford F-150 truck?",
        "expected_tool": "pos_troubleshooting_rag_tool (fallback warning)"
    },
    {
        "id": "UC 1.2a",
        "category": "Stockout Risk (<20h)",
        "prompt": "What is the estimated cover hours remaining for store inventory positions experiencing stockout risk of less than 20 hours, and what is their total on-hand inventory?",
        "expected_tool": "cymbal_analytics_tool"
    },
    {
        "id": "UC 1.3",
        "category": "Real-Time Cashier Metrics",
        "prompt": "Read live 1-hour rolling metrics and audit status flags for Cashier CASH_1190 at Store 48.",
        "expected_tool": "query_bigtable_cashier_metrics"
    },
    {
        "id": "UC 2.1a",
        "category": "Warranty Transaction",
        "prompt": "Check transaction details for TXN-20260312-0015811 and show the warranty coverage policy for the purchased item.",
        "expected_tool": "cymbal_analytics_tool"
    },
    {
        "id": "UC 2.2",
        "category": "Dual Cashier Baseline",
        "prompt": "What is Cashier CASH_1190's live 1-hour override rate right now, compared to their 7-day historical override baseline?",
        "expected_tool": "PARALLEL: query_bigtable_cashier_metrics + cymbal_analytics_tool"
    },
    {
        "id": "UC 2.3",
        "category": "Cross-Cloud Offender Audit",
        "prompt": "Show cashiers with active cashier promo abuse alerts in the last 7 days and retrieve checkout logs for the top offender.",
        "expected_tool": "SEQUENTIAL: cymbal_analytics_tool (Turn 1 GCP alerts -> Turn 2 AWS S3 logs)"
    }
]

def main():
    print("=" * 80)
    print("CYMBAL RETAIL OPERATIONS AGENT - VALIDATION TEST SUITE")
    print("=" * 80)

    for s in SCENARIOS:
        print(f"\n[{s['id']}] Category: {s['category']}")
        print(f"Prompt: \"{s['prompt']}\"")
        print(f"Expected Routing: {s['expected_tool']}")
        print("-" * 80)

    print("\nTo run interactive evaluation:")
    print("  adk web app")
    print("Then open your browser to the local ADK Web UI.")

if __name__ == "__main__":
    main()
