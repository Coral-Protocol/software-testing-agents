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
from langchain_community.callbacks import get_openai_callback
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
    "waitForAgents": 1,
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


async def create_codediff_review_agent(client, tools):
    prompt = ChatPromptTemplate.from_messages([
        ("system", f"""You are `codediff_review_agent`, responsible for retrieving and formatting code diffs from a GitHub pull request.

        1. Use `wait_for_mentions(timeoutMs=60000)` to wait for instructions from other agents.
        2. When a mention is received, record the `threadId` and `senderId`.
        3. Check if the message asks to analyze a PR with a repo name and PR number.
        4. Extract `repo_name` and `pr_number` from the message.
        5. Call `get_pull_request_files(pullNumber=pr_number, repo=repo_name)` to get code diffs.
        6. If this call fails, send the error message using `send_message` to the sender.
        7. If successful, send the formatted code diffs using `send_message` to the sender.
        8. If the message format is invalid or parsing fails, skip it silently.
        9. Do not create threads; always use the `threadId` from the mention.
        10. Wait 2 seconds and repeat from step 1.  Tools: {get_tools_description(tools)}"""),
        ("placeholder", "{agent_scratchpad}")
    ])

    model = ChatOpenAI(
        model="gpt-4.1-2025-04-14",
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=0.3,
        max_tokens=8192
    )

    #model = ChatOllama(model="llama3")

    agent = create_tool_calling_agent(model, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=True)

async def main():
    max_retries = 5
    retry_delay = 5  # seconds

    github_token = os.getenv("GITHUB_ACCESS_TOKEN")
    if not github_token:
        raise ValueError("GITHUB_PERSONAL_ACCESS_TOKEN environment variable is required")

    for attempt in range(max_retries):
        try:
            async with MultiServerMCPClient(
                connections = {
                    "coral": {
                        "transport": "sse", 
                        "url": MCP_SERVER_URL, 
                        "timeout": 300, 
                        "sse_read_timeout": 300
                    },
                    "github": {
                        "transport": "stdio",
                        "command": "docker",
                        "args": [
                            "run",
                            "-i",
                            "--rm",
                            "-e",
                            "GITHUB_PERSONAL_ACCESS_TOKEN",
                            "ghcr.io/github/github-mcp-server"
                        ],
                        "env": {
                            "GITHUB_PERSONAL_ACCESS_TOKEN": github_token
                        }
                    }
                }
            ) as client:
                logger.info(f"Connected to MCP server at {MCP_SERVER_URL}")
                coral_tool_names = [
                    "list_agents",
                    "create_thread",
                    "add_participant",
                    "remove_participant",
                    "close_thread",
                    "send_message",
                    "wait_for_mentions",
                    # 如果还有其它 coral 工具，补充在这里
                ]

                # 获取并筛选
                all_tools = client.get_tools()

                tools = [
                    tool for tool in all_tools
                    if tool.name in coral_tool_names or tool.name == "get_pull_request_files"
                ]

                logger.info(f"Tools Description:\n{get_tools_description(tools)}")

                # 使用 get_openai_callback 追踪 token 使用情况
                with get_openai_callback() as cb:
                    agent_executor = await create_codediff_review_agent(client, tools)
                    await agent_executor.ainvoke({})
                    logger.info(f"Token usage for this run:")
                    logger.info(f"  Prompt Tokens: {cb.prompt_tokens}")
                    logger.info(f"  Completion Tokens: {cb.completion_tokens}")
                    logger.info(f"  Total Tokens: {cb.total_tokens}")
                    logger.info(f"  Total Cost (USD): ${cb.total_cost:.6f}")
        except ClosedResourceError as e:
            logger.error(f"ClosedResourceError on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
                continue
            else:
                logger.error("Max retries reached. Exiting.")
                raise
        except Exception as e:
            logger.error(f"Unexpected error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
                continue
            else:
                logger.error("Max retries reached. Exiting.")
                raise

if __name__ == "__main__":
    asyncio.run(main())
