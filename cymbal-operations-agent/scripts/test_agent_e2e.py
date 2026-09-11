"""End-to-End Async Orchestration Validation for Cymbal Retail Operations Agent."""

import asyncio
import os
import sys
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agent import root_agent

SCENARIOS = [
    {
        "id": "UC 1.1a",
        "category": "Hardware Error Runbook Retrieval",
        "prompt": "What is the immediate field recovery protocol when a cashier encounters an ERR-PAY-4001 EMV contactless payment freeze, and how do we ensure the customer is not double-charged?"
    },
    {
        "id": "UC 1.1c",
        "category": "Out-of-Scope Hardware Guardrail",
        "prompt": "How do I replace the engine oil on a Ford F-150 truck?"
    },
    {
        "id": "UC 1.2a",
        "category": "Stockout Risk (<20h Cover)",
        "prompt": "What is the estimated cover hours remaining for store inventory positions experiencing stockout risk of less than 20 hours, and what is their total on-hand inventory?"
    },
    {
        "id": "UC 1.3",
        "category": "Real-Time Cashier Metrics (Bigtable)",
        "prompt": "Read live 1-hour rolling metrics and audit status flags for Cashier CASH_1190 at Store 48."
    },
    {
        "id": "UC 2.1a",
        "category": "Warranty Transaction Verification",
        "prompt": "Check transaction details for TXN-20260312-0015811 and show the warranty coverage policy for the purchased item."
    },
    {
        "id": "UC 2.2",
        "category": "Dual Cashier Baseline (Parallel Dispatch)",
        "prompt": "What is Cashier CASH_1190's live 1-hour override rate right now, compared to their 7-day historical override baseline?"
    },
    {
        "id": "UC 2.3",
        "category": "Cross-Cloud Promo Offender Audit (Sequential Multi-Turn)",
        "prompt": "Show cashiers with active cashier promo abuse alerts in the last 7 days and retrieve checkout logs for the top offender."
    }
]


async def run_scenario(scenario, runner, session_service):
    print("=" * 80)
    print(f"RUNNING SCENARIO [{scenario['id']}]: {scenario['category']}")
    print(f"Prompt: \"{scenario['prompt']}\"")
    print("=" * 80)

    session = await session_service.create_session(
        user_id="test_auditor",
        app_name="app"
    )

    user_msg = types.Content(
        role="user",
        parts=[types.Part.from_text(text=scenario["prompt"])]
    )

    t0 = time.time()
    events = []
    async for event in runner.run_async(
        new_message=user_msg,
        user_id="test_auditor",
        session_id=session.id
    ):
        events.append(event)
        if event.content and event.content.parts:
            for part in event.content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    print(f"  ⚡ [Tool Call]: {part.function_call.name}({part.function_call.args})")
                elif hasattr(part, "function_response") and part.function_response:
                    res_str = str(part.function_response.response)[:200]
                    print(f"  📥 [Tool Response]: {res_str}...")

    elapsed = time.time() - t0
    print(f"\nCompleted in {elapsed:.2f}s across {len(events)} events.")

    for event in events:
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(f"\n--- Coordinator Synthesis [{scenario['id']}] ---:\n{part.text.strip()}\n" + "-" * 80)


async def main():
    print("=" * 80)
    print("CYMBAL OPERATIONS AGENT - FULL OPERATIONAL VALIDATION SUITE")
    print("=" * 80)

    session_service = InMemorySessionService()
    runner = Runner(agent=root_agent, session_service=session_service, app_name="app")

    for s in SCENARIOS:
        try:
            await run_scenario(s, runner, session_service)
        except Exception as e:
            print(f"❌ FAILED scenario {s['id']}: {e}")
        print("\n\n")


if __name__ == "__main__":
    asyncio.run(main())
