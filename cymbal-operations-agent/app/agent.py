"""Cymbal Retail Operations Coordinator Agent."""

import os
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from app.prompts import SYSTEM_INSTRUCTIONS
from app.tools.analytics_tool import cymbal_analytics_tool
from app.tools.rag_tool import pos_troubleshooting_rag_tool
from app.tools.bigtable_tool import bigtable_mcp_toolset, read_pos_transactions_tool

MODEL_NAME = os.getenv("COORDINATOR_MODEL", "gemini-3.6-flash")

root_agent = Agent(
    name="cymbal_operations_agent",
    model=Gemini(
        model=MODEL_NAME,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=SYSTEM_INSTRUCTIONS,
    tools=[
        cymbal_analytics_tool,
        pos_troubleshooting_rag_tool,
        bigtable_mcp_toolset,
        read_pos_transactions_tool
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
