import asyncio
import os
import json
import logging
import re
import difflib
from typing import List, Dict
import subprocess
from github import Github
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
    "waitForAgents": 2,
    "agentId": "gitclone_agent",
    "agentDescription": "You are gitclone_agent, responsible for cloning a GitHub repository and checking out the branch associated with a specific pull request."
}
query_string = urllib.parse.urlencode(params)
MCP_SERVER_URL = f"{base_url}?{query_string}"
AGENT_NAME = "gitclone_agent"

# Validate API keys
if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY is not set in environment variables.")

def get_tools_description(tools):
    return "\n".join(f"Tool: {t.name}, Schema: {json.dumps(t.args).replace('{', '{{').replace('}', '}}')}" for t in tools)

@tool
def checkout_github_pr(repo_full_name: str, pr_number: int) -> str:
    """
    Clone a GitHub repository and check out the branch associated with a specific pull request.

    Args:
        repo_full_name (str): GitHub repository in the format "owner/repo".
        pr_number (int): Pull request number.

    Returns:
        str: Absolute path to the local repository checked out to the PR branch.
    """
    dest_dir = os.getcwd()

    repo_name = repo_full_name.split('/')[-1]
    repo_url = f'https://github.com/{repo_full_name}.git'
    repo_path = os.path.join(dest_dir, repo_name)
    pr_branch = f'pr-{pr_number}'

    if not os.path.exists(repo_path):
        subprocess.run(['git', 'clone', repo_url, repo_path], check=True)

    try:
        subprocess.run(['git', '-C', repo_path, 'checkout', 'main'], check=True)
    except subprocess.CalledProcessError:
        try:
            subprocess.run(['git', '-C', repo_path, 'checkout', 'master'], check=True)
        except subprocess.CalledProcessError:
            pass  # Continue if neither branch exists

    existing_branches = subprocess.run(['git', '-C', repo_path, 'branch'], capture_output=True, text=True).stdout
    if pr_branch in existing_branches:
        subprocess.run(['git', '-C', repo_path, 'branch', '-D', pr_branch], check=True)

    subprocess.run(['git', '-C', repo_path, 'fetch', 'origin', f'pull/{pr_number}/head:{pr_branch}'], check=True)
    subprocess.run(['git', '-C', repo_path, 'checkout', pr_branch], check=True)

    return os.path.abspath(repo_path)



async def create_gitclone_agent(client, tools):
    prompt = ChatPromptTemplate.from_messages([
        ("system", f"""You are gitclone_agent, responsible for cloning a GitHub repository and checking out the branch associated with a specific pull request.

        **Initialization**:
        1. Ensure you are registered using list_agents. If not, register using:
        register_agent(agentId: 'gitclone_agent', agentName: 'Git Clone Agent', description: 'Clones GitHub repositories and checks out the branch for a specific Pull Request.')

        **Loop**:
        1. Call wait_for_mentions ONCE (agentId: 'gitclone_agent', timeoutMs: 30000).

        2. For mentions from 'user_interaction_agent' containing:  
        "Checkout PR #[pr_number] from '[repo]'":
        - Extract:
            - pr_number (e.g., 42)
            - repo (e.g., 'octocat/calculator')
        - Call checkout_github_pr(repo_full_name=repo, pr_number=pr_number) from your tools.
        - If successful, send the result via send_message (senderId: 'gitclone_agent', mentions: ['user_interaction_agent']) with content:
            ```
            Successfully checked out PR #[pr_number] from '[repo]'.
            Local path: [repo_path]
            ```
        - If the tool fails, send the error message via send_message (senderId: 'gitclone_agent', mentions: ['user_interaction_agent']).

        3. If the mention format is invalid or incomplete, continue the loop without responding.

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
                tools = client.get_tools() + [checkout_github_pr]
                logger.info(f"Connected to MCP server. Tools:\n{get_tools_description(tools)}")
                retries = max_retries  # Reset retries on successful connection
                await (await create_gitclone_agent(client, tools)).ainvoke({})
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