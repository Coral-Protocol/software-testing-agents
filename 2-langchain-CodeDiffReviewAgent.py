import asyncio
import os
import json
import logging
import re
import difflib
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
    "waitForAgents": 3,
    "agentId": "codediff_review_agent",
    "agentDescription": "You are codediff_review_agent, responsible for analyzing function-level differences between two Python files"
}
query_string = urllib.parse.urlencode(params)
MCP_SERVER_URL = f"{base_url}?{query_string}"
AGENT_NAME = "codediff_review_agent"

# Validate API keys
if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY is not set in environment variables.")

def get_tools_description(tools):
    return "\n".join(f"Tool: {t.name}, Schema: {json.dumps(t.args).replace('{', '{{').replace('}', '}}')}" for t in tools)

@tool
def compare_python_files(file1: str = "./user_code/calculator.py", file2: str = "./user_code/calculator_PR.py") -> dict:
    """
    Compare two Python files and return a unified diff of their differences.

    Args:
        file1 (str): Path to the original Python file (e.g., './user_code/calculator.py').
        file2 (str): Path to the modified Python file (e.g., './user_code/calculator_PR.py').

    Returns:
        dict: Contains 'result' key with either a unified diff string or a no-difference message.
    """

    with open(file1, 'r') as f1, open(file2, 'r') as f2:
        code1_lines = f1.readlines()
        code2_lines = f2.readlines()

    diff = difflib.unified_diff(
        code1_lines, code2_lines,
        fromfile=file1,
        tofile=file2,
        lineterm=''
    )

    diff_output = list(diff)
    if not diff_output:
        result = "The two files are identical."
    else:
        result = "\n".join(diff_output)

    print("Differences:\n" + result)
    return {"result": result}


async def create_codediff_review_agent(client, tools):
    prompt = ChatPromptTemplate.from_messages([
        ("system", f"""You are codediff_review_agent, responsible for analyzing function-level differences between two Python files.

        **Initialization**:
        1. Ensure you are registered using list_agents. If not, register using:
        register_agent(agentId: 'codediff_review_agent', agentName: 'Code Diff Review Agent', description: 'Compares two Python files and identifies which functions changed.')

        **Loop**:
        1. Call wait_for_mentions ONCE (agentId: 'codediff_review_agent', timeoutMs: 8000).
        2. For mentions from 'user_interaction_agent' containing: 'Analyze the diff between [file1] and [file2]':
        - Extract the file names.
        - Call compare_python_files(file1, file2) from your tools.
        - If result contains changed functions, extract them (e.g., multiply) and map them to their corresponding test (e.g., test_multiply).
        - Send results or error to the mentioned thread via send_message (senderId: 'codediff_review_agent', mentions: ['user_interaction_agent']).
        3. If invalid input or no mentions, repeat loop.

        Do not create threads. Track threadId from mentions. Tools: {get_tools_description(tools)}"""),
        ("placeholder", "{agent_scratchpad}")
    ])

    model = ChatOpenAI(
        model="gpt-4o-mini",
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
                tools = client.get_tools() + [compare_python_files]
                logger.info(f"Connected to MCP server. Tools:\n{get_tools_description(tools)}")
                retries = max_retries  # Reset retries on successful connection
                await (await create_codediff_review_agent(client, tools)).ainvoke({})
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