"""Cymbal Retail Operations Coordinator Agent."""

import os
from dotenv import load_dotenv

load_dotenv(override=True)

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.plugins.bigquery_agent_analytics_plugin import BigQueryAgentAnalyticsPlugin
from google.genai import types

from app.prompts import SYSTEM_INSTRUCTIONS
from app.tools.analytics_tool import cymbal_analytics_tool
from app.tools.rag_tool import pos_troubleshooting_rag_tool
from app.tools.bigtable_tool import bigtable_mcp_toolset, read_pos_transactions_tool

MODEL_NAME = os.getenv("COORDINATOR_MODEL", "gemini-3.6-flash")
PROJECT_ID = os.getenv("PROJECT_ID", "praxis-magnet-508004-d7")
BQ_TELEMETRY_DATASET = os.getenv("BQ_TELEMETRY_DATASET", "agent_telemetry")
REGION = os.getenv("REGION", "us-central1")

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
        read_pos_transactions_tool,
    ],
)

analytics_plugin = BigQueryAgentAnalyticsPlugin(
    project_id=PROJECT_ID,
    dataset_id=BQ_TELEMETRY_DATASET,
    location=REGION,
)

app = App(
    root_agent=root_agent,
    name="app",
    plugins=[analytics_plugin],
)

