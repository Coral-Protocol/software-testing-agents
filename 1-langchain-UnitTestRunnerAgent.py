import asyncio
import os
import json
import logging
import subprocess
import sys
import re
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.tools import tool
from dotenv import load_dotenv
from anyio import ClosedResourceError
import urllib.parse

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

base_url = "http://localhost:5555/devmode/exampleApplication/privkey/session1/sse"
params = {
    "waitForAgents": 2,
    "agentId": "unit_test_runner_agent",
    "agentDescription": "You are unit_test_runner_agent, responsible for executing a specific pytest test based on function name"
}
query_string = urllib.parse.urlencode(params)
MCP_SERVER_URL = f"{base_url}?{query_string}"
AGENT_NAME = "unit_test_runner_agent"

# Validate API keys
if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY is not set in environment variables.")

def get_tools_description(tools):
    return "\n".join(f"Tool: {t.name}, Schema: {json.dumps(t.args).replace('{', '{{').replace('}', '}}')}" for t in tools)

@tool
def run_test(test_name: str) -> dict:
    """
    Run a specific pytest unit test function from the test_calculator.py file.

    Args:
        test_name (str): Name of the test function to run (e.g., 'test_add', 'test_subtract', 'test_multiply').

    Returns:
        dict: Contains 'result' message, 'output' (full pytest output), and 'status' (True if passed).
    """

    test_path = f"tests/test_calculator.py::{test_name}"
    command = ["pytest", test_path]
    env = {"PYTHONPATH": "."}

    print(f"Running: pytest {test_path}")
    result = subprocess.run(command, env={**env, **dict(**os.environ)}, capture_output=True, text=True)

    print("--- Pytest Output ---")
    print(result.stdout)

    passed = result.returncode == 0
    status_msg = "Test passed." if passed else "Test failed."

    return {
        "result": status_msg,
        "output": result.stdout,
        "status": passed
    }

async def create_unit_test_runner_agent(client, tools):
    prompt = ChatPromptTemplate.from_messages([
        ("system", f"""You are unit_test_runner_agent, responsible for executing a specific pytest test based on function name.

        **Initialization**:
        1. Ensure you are registered using list_agents. If not, register using:
        register_agent(agentId: 'unit_test_runner_agent', agentName: 'Unit Test Runner Agent', description: 'Runs specified pytest unit tests and returns results.')

        **Loop**:
        1. Call wait_for_mentions ONCE (agentId: 'unit_test_runner_agent', timeoutMs: 8000).
        2. For mentions from 'user_interaction_agent' containing 'Please run unit test: [test_name]':
        - Extract test name (e.g., test_multiply)
        - Call run_test(test_name) from your tools.
        - Send test results or error to the mentioned thread via send_message (senderId: 'unit_test_runner_agent', mentions: ['user_interaction_agent']).
        3. If input is invalid or missing, do nothing and continue loop.

        Do not create threads. Track threadId from mentions. Tools: {get_tools_description(tools)}"""),
        ("placeholder", "{agent_scratchpad}")
    ])

    model = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY"), temperature=0.3, max_tokens=4096)
    agent = create_tool_calling_agent(model, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=True)

async def main():
    retry_delay = 5  # seconds
    max_retries = 5
    retries = max_retries

    while retries > 0:
        try:
            async with MultiServerMCPClient(connections={
                "coral": {"transport": "sse", "url": MCP_SERVER_URL, "timeout": 30, "sse_read_timeout": 60}
            }) as client:
                tools = client.get_tools() + [run_test]
                logger.info(f"Connected to MCP server. Tools:\n{get_tools_description(tools)}")
                retries = max_retries  # Reset retries on successful connection
                await (await create_unit_test_runner_agent(client, tools)).ainvoke({})
        except ClosedResourceError as e:
            retries -= 1
            logger.error(f"Connection closed: {str(e)}. Retries left: {retries}. Retrying in {retry_delay} seconds...")
            if retries == 0:
                logger.error("Max retries reached. Exiting.")
                break
            await asyncio.sleep(retry_delay)
        except Exception as e:
            retries -= 1
            logger.error(f"Unexpected error: {str(e)}. Retries left: {retries}. Retrying in {retry_delay} seconds...")
            if retries == 0:
                logger.error("Max retries reached. Exiting.")
                break
            await asyncio.sleep(retry_delay)

if __name__ == "__main__":
    asyncio.run(main())