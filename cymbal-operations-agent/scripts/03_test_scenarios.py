"""Operational Test Scenarios Runner with Formal Assertions for Cymbal Retail Operations Agent."""

import asyncio
import logging
import os
import sys
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from app.agent import root_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SCENARIOS = [
    {
        "id": "UC 1.1a",
        "category": "Hardware Error",
        "prompt": "What is the immediate field recovery protocol when a cashier encounters an ERR-PAY-4001 EMV contactless payment freeze, and how do we ensure the customer is not double-charged?",
        "expected_tool": "pos_troubleshooting_rag_tool",
        "assert_contains": ["ERR-PAY-4001", "payment"]
    },
    {
        "id": "UC 1.1c",
        "category": "Out-of-Scope Hardware",
        "prompt": "How do I replace the engine oil on a Ford F-150 truck?",
        "expected_tool": "pos_troubleshooting_rag_tool",
        "assert_contains": ["I cannot find certified warranty or repair rules for this specific error in our technical repository."]
    },
    {
        "id": "UC 1.2a",
        "category": "Stockout Risk (<20h)",
        "prompt": "What is the estimated cover hours remaining for store inventory positions experiencing stockout risk of less than 20 hours, and what is their total on-hand inventory?",
        "expected_tool": "cymbal_analytics_tool",
        "assert_contains": ["cover", "inventory"]
    },
    {
        "id": "UC 1.3",
        "category": "Real-Time Cashier Metrics",
        "prompt": "Read live 1-hour rolling metrics and audit status flags for Cashier CASH_1190 at Store 48.",
        "expected_tool": "query_bigtable_cashier_metrics",
        "assert_contains": ["CASH_1190", "clear"]
    },
    {
        "id": "UC 2.1a",
        "category": "Warranty Transaction",
        "prompt": "Check transaction details for TXN-20260312-0015811 and show the warranty coverage policy for the purchased item.",
        "expected_tool": "cymbal_analytics_tool",
        "assert_contains": ["TXN-20260312-0015811"]
    },
    {
        "id": "UC 2.2",
        "category": "Dual Cashier Baseline",
        "prompt": "What is Cashier CASH_1190's live 1-hour override rate right now, compared to their 7-day historical override baseline?",
        "expected_tool": "query_bigtable_cashier_metrics",
        "assert_contains": ["CASH_1190"]
    },
    {
        "id": "UC 2.3",
        "category": "Cross-Cloud Offender Audit",
        "prompt": "Show cashiers with active cashier promo abuse alerts in the last 7 days and retrieve checkout logs for the top offender.",
        "expected_tool": "cymbal_analytics_tool",
        "assert_contains": ["promo", "cashier"]
    }
]


async def run_and_assert_scenario(scenario, runner, session_service):
    logger.info(f"Running [{scenario['id']}] {scenario['category']}...")
    session = await session_service.create_session(
        user_id="test_auditor",
        app_name="app"
    )

    user_msg = types.Content(
        role="user",
        parts=[types.Part.from_text(text=scenario["prompt"])]
    )

    events = []
    final_text = ""
    tools_called = []

    async for event in runner.run_async(
        new_message=user_msg,
        user_id="test_auditor",
        session_id=session.id
    ):
        events.append(event)
        if event.content and event.content.parts:
            for part in event.content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    tools_called.append(part.function_call.name)
                if hasattr(part, "text") and part.text:
                    final_text += part.text + "\n"

    assert len(events) > 0, f"[{scenario['id']}] No events emitted by agent runner."
    assert len(final_text.strip()) > 0, f"[{scenario['id']}] Empty synthesis output."

    for expected_str in scenario["assert_contains"]:
        assert expected_str.lower() in final_text.lower(), (
            f"[{scenario['id']}] Assertion failed: '{expected_str}' not found in agent output: {final_text[:300]}..."
        )

    logger.info(f"✅ [{scenario['id']}] PASSED. Tools called: {tools_called}")
    return True


async def main_async():
    session_service = InMemorySessionService()
    runner = Runner(agent=root_agent, session_service=session_service, app_name="app")

    passed = 0
    failed = 0

    print("=" * 80)
    print("CYMBAL RETAIL OPERATIONS AGENT - VALIDATION TEST SUITE WITH ASSERTIONS")
    print("=" * 80)

    for scenario in SCENARIOS:
        try:
            await run_and_assert_scenario(scenario, runner, session_service)
            passed += 1
        except Exception as e:
            logger.error(f"❌ [{scenario['id']}] FAILED: {e}")
            failed += 1

    print("=" * 80)
    print(f"TEST RESULTS: {passed} PASSED, {failed} FAILED across {len(SCENARIOS)} scenarios.")
    print("=" * 80)

    if failed > 0:
        sys.exit(1)


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
