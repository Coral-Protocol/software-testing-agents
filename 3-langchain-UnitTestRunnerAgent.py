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
from langchain_ollama.chat_models import ChatOllama
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
    "waitForAgents": 4,
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
def run_test(project_root: str, relative_test_path: str, test_name: str) -> dict:
    """
    Run a specific pytest unit test function from a test file within a project directory.

    Args:
        project_root (str): Absolute path to the project root directory.
        relative_test_path (str): Path to the test file relative to the project root.
        test_name (str): Name of the test function to run (e.g., 'test_add', 'test_subtract', 'test_multiply').

    Returns:
        dict: Contains 'result' message, 'output' (full pytest output), and 'status' (True if passed).
    """
    if not os.path.isabs(project_root):
        raise ValueError("project_root must be an absolute path.")

    abs_test_path = os.path.join(project_root, relative_test_path)

    if not os.path.exists(abs_test_path):
        raise FileNotFoundError(f"Test file does not exist: {abs_test_path}")

    pytest_target = f"{relative_test_path}::{test_name}"

    command = ["pytest", pytest_target]
    env = os.environ.copy()
    env["PYTHONPATH"] = project_root

    print(f"Running pytest: {pytest_target}")
    result = subprocess.run(command, cwd=project_root, env=env, capture_output=True, text=True)

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
        ("system", f"""You are unit_test_runner_agent, responsible for executing a specific pytest unit test given the project root path, test file, and test function name.

        **Initialization**:
        1. Ensure you are registered using list_agents. If not, register using:
        register_agent(agentId: 'unit_test_runner_agent', agentName: 'Unit Test Runner Agent', description: 'Runs a specified pytest unit test and returns structured results.')

        **Loop**:
        1. Call wait_for_mentions ONCE (agentId: 'unit_test_runner_agent', timeoutMs: 30000).

        2. For mentions from 'user_interaction_agent' containing:  
        "Please run unit test '[test_name]' located in '[relative_test_path]' under project root '[project_root]'":
        - Extract the following:
            - test_name (e.g., 'test_multiply')
            - relative_test_path (e.g., 'tests/test_calculator.py') from the test file path
            - project_root (e.g., '/tmp/octocat/calculator') from the GitCloneAgent result
        - Call run_test(project_root, relative_test_path, test_name) from your tools.
            - If the tool fails (e.g., file not found), send the error message via send_message (senderId: 'unit_test_runner_agent', mentions: ['user_interaction_agent']).
        - Format reply as:
            ```
            Test result: [status]
            Output:
            [pytest stdout]
            ```
        - Send the result via send_message (senderId: 'unit_test_runner_agent', mentions: ['user_interaction_agent']).

        3. If the mention format is invalid or missing, continue the loop silently.

        Do not create threads. Track threadId from mentions. Tools: {get_tools_description(tools)}"""),
        ("placeholder", "{agent_scratchpad}")
    ])

    model = ChatOpenAI(
        model="gpt-4.1-mini-2025-04-14",
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=0.3,
        max_tokens=8192  # or 16384, 32768 depending on your needs; for gpt-4o-mini, make sure prompt + history + output < 128k tokens
    )

    #model = ChatOllama(model="llama3")

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