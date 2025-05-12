import asyncio
import os
import json
import logging
import re
import difflib
from typing import List, Dict
from github import Github
from github.ContentFile import ContentFile
from github.GithubException import GithubException
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
    "agentDescription": "You are codediff_review_agent, responsible for analyzing code changes in GitHub Pull Requests and identifying which functions have been modified, which tests should be executed, and where those tests are located in the repository."
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
def get_pr_code_changes(repo_name: str, pr_number: int) -> List[Dict[str, str]]:
    """
    Fetch the code changes (diffs) for a specific Pull Request by its number.

    Args:
        repo_name (str): Full repository name in the form "owner/repo".
        pr_number (int): The number of the Pull Request.

    Returns:
        List[Dict[str, str]]: A list of dicts, each containing:
            - "filename": The path of the changed file.
            - "patch": The diff content for that file.

    Raises:
        ValueError: If access token is not available or PR not found.
        GithubException: On GitHub API errors (e.g., invalid repo name).
    """
    token = os.getenv("GITHUB_ACCESS_TOKEN")
    if not token:
        raise ValueError("GITHUB_ACCESS_TOKEN environment variable is not set.")

    # Initialize GitHub client
    gh = Github(token)

    try:
        repo = gh.get_repo(repo_name)
    except GithubException as e:
        raise GithubException(f"Failed to open repository '{repo_name}': {e.data}")

    try:
        pr = repo.get_pull(pr_number)
    except GithubException as e:
        raise GithubException(f"Failed to retrieve PR #{pr_number} from '{repo_name}': {e.data}")

    changes = []
    for file in pr.get_files():
        changes.append({
            "filename": file.filename,
            "patch": file.patch or ""
        })

    return changes

async def create_codediff_review_agent(client, tools):
    prompt = ChatPromptTemplate.from_messages([
        ("system", f"""You are codediff_review_agent, responsible for retrieving all code diffs from a GitHub Pull Request and formatting them for further processing.

        **Initialization**:
        1. Ensure you are registered using list_agents. If not, register using:
        register_agent(agentId: 'codediff_review_agent', agentName: 'Code Diff Review Agent', description: 'Fetches and formats code diffs from GitHub pull requests.')

        **Loop**:
        1. Call wait_for_mentions ONCE (agentId: 'codediff_review_agent', timeoutMs: 30000).

        2. For mentions from 'user_interaction_agent' containing:  
        "Analyze PR #[pr_number] from '[repo_name]'":

        - Extract:
            - `repo_name` (e.g., "octocat/calculator")
            - `pr_number` (e.g., 42)

        - Call `get_pr_code_changes(repo_name, pr_number)` to retrieve code diffs.

        - If the tool fails (e.g., network or auth error), send the error message using:
            `send_message(senderId: 'codediff_review_agent', mentions: ['user_interaction_agent'])`.

        - For each changed file in the result:
            - Extract:
            - `filename` (e.g., "calculator.py")
            - `patch` (diff content)

        - Format the reply as:
            ```
            File: [filename_1]
            [patch_1]

            File: [filename_2]
            [patch_2]

            ...
            ```

        - Send the result using `send_message(senderId: 'codediff_review_agent', mentions: ['user_interaction_agent'])`.

        3. If the mention format is invalid or parsing fails, continue the loop silently.

        4. Do not create threads. Track `threadId` from mentions. Tools: {get_tools_description(tools)}"""),
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
                tools = client.get_tools() + [get_pr_code_changes]
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