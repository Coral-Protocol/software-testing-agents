import asyncio
import os
import json
import logging
from typing import List
from github import Github
from github.ContentFile import ContentFile
from github.GithubException import GithubException
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.tools import tool
from langchain_community.callbacks import get_openai_callback
from dotenv import load_dotenv
from anyio import ClosedResourceError
import urllib.parse
import base64

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

base_url = "http://localhost:5555/devmode/exampleApplication/privkey/session1/sse"
params = {
    "waitForAgents": 1,
    "agentId": "repo_understanding_agent",
    "agentDescription": "You are `repo_understanding_agent`, responsible for comprehensively analyzing a GitHub repository using only the available tools.."
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
def decode_base64_content(
    base64_content: str,
    encoding: str = "utf-8"
) -> str:
    """
    Decode a base64-encoded string to its original text.

    Args:
        base64_content (str): The base64-encoded content.
        encoding (str, optional): The target character encoding, default is "utf-8".

    Returns:
        str: The decoded text content.
    
    Raises:
        ValueError: If the input is not valid base64 or can't be decoded.
    """
    try:
        decoded_bytes = base64.b64decode(base64_content.strip())
        return decoded_bytes.decode(encoding)
    except Exception as e:
        raise ValueError(f"Failed to decode base64 content: {e}")
    
@tool
def get_all_github_files(repo_name: str, branch: str = "main") -> List[str]:
    """
    Recursively retrieve all file paths from a specific branch of a GitHub repository.

    Args:
        repo_name (str): Full repository name in the format "owner/repo".
        branch (str): Branch name to retrieve files from. Defaults to "main".

    Returns:
        List[str]: A list of all file paths in the specified branch of the repository.

    Raises:
        ValueError: If GITHUB_ACCESS_TOKEN is not set.
        GithubException: On repository access or API failure.
    """
    token = os.getenv("GITHUB_ACCESS_TOKEN")
    if not token:
        raise ValueError("GITHUB_ACCESS_TOKEN environment variable is not set.")

    gh = Github(token)

    try:
        repo = gh.get_repo(repo_name)
    except GithubException as e:
        raise GithubException(f"Failed to access repository '{repo_name}': {e.data}")

    def get_all_file_paths(path: str = "") -> List[str]:
        files: List[str] = []
        try:
            contents = repo.get_contents(path, ref=branch)
        except GithubException as e:
            raise GithubException(f"Failed to get contents of path '{path}' in branch '{branch}': {e.data}")

        if isinstance(contents, ContentFile):
            files.append(contents.path)
        else:
            for content in contents:
                if content.type == "dir":
                    files.extend(get_all_file_paths(content.path))
                else:
                    files.append(content.path)
        return files

    return get_all_file_paths()


@tool
def retrieve_github_file_content(repo_name: str, file_path: str, branch: str = "main") -> str:
    """
    Retrieve the content of a specific file from a specific branch of a GitHub repository.

    Args:
        repo_name (str): Full repository name in the format "owner/repo".
        file_path (str): Path to the file in the repository.
        branch (str): Branch name to retrieve the file from. Defaults to "main".

    Returns:
        str: The decoded content of the file.

    Raises:
        ValueError: If GITHUB_ACCESS_TOKEN is not set.
        GithubException: On repository access or API failure.
        ValueError: If multiple files are returned (e.g., by mistake).
    """
    token = os.getenv("GITHUB_ACCESS_TOKEN")
    if not token:
        raise ValueError("GITHUB_ACCESS_TOKEN environment variable is not set.")

    gh = Github(token)
    try:
        repo = gh.get_repo(repo_name)
    except GithubException as e:
        raise GithubException(f"Failed to access repository '{repo_name}': {e.data}")

    try:
        file_content = repo.get_contents(file_path, ref=branch)
    except GithubException as e:
        raise GithubException(f"Failed to get content of file '{file_path}' in branch '{branch}': {e.data}")

    if isinstance(file_content, ContentFile):
        return file_content.decoded_content.decode()
    else:
        raise ValueError("PRs or requests that return multiple files aren't supported yet.")

async def create_codediff_review_agent(client, tools):
    prompt = ChatPromptTemplate.from_messages([
        ("system", f"""You are `repo_understanding_agent`, responsible for comprehensively analyzing a GitHub repository using only the available tools. Follow this workflow:

        1. Use `wait_for_mentions(timeoutMs=30000)` to wait for instructions from other agents.**
        2. When a mention is received, record the `threadId` and `senderId`.
        3. Check if the message contains a `repo` name, `owner`, and a target `branch`.
        4. Call `get_all_github_files(repo_name = ..., branch = ...)` to list all files.
        5. Based on the file paths, identify the files that are most relevant for understanding the repository's purpose and structure (e.g., `README.md`, `setup.py`, main source code files, configuration files, test files, etc.).
        6. For these selected files, use `retrieve_github_file_content(repo_name = ..., file_path = ..., branch = ...)` to retrieve their content, **please only open one file each time**
        -Analyze the decoded content to extract:
            - The overall project purpose and main functionality.
            - The primary components/modules and their roles.
            - How to use or run the project (if available).
            - Any noteworthy implementation details or structure.
        7. Once you have gained sufficient understanding of the repository, summarize your findings clearly and concisely.
        8. Use `send_message(senderId=..., mentions=[senderId], threadId=..., content="your summary")` to reply to the sender with your analysis.
        9. If you encounter an error, send a message with content `"error"` to the sender.
        10. Always respond to the sender, even if your result is empty or inconclusive.
        11. Wait 2 seconds and repeat from step 1.

        **Note: Each ten time you call any tool, you need to call `recall_system_message()` to recall system message**
        
        Tools: {get_tools_description(tools)}, Tool: recall_system_message  
        Schema: (
        "system_message": (
            "title": "System Message",
            "type": "string"
        )
        )"""),
        ("placeholder", "{agent_scratchpad}")
    ])

    model = ChatOpenAI(
        model="gpt-4.1-2025-04-14",
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=0.3,
        max_tokens=32768
    )


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
                ]

                tools = client.get_tools()

                tools = [
                    tool for tool in tools
                    if tool.name in coral_tool_names
                ]

                tools += [get_all_github_files, retrieve_github_file_content]

                AGENT_SYSTEM_PROMPT = f"""
                **It is a message for you to recall the system message**
                You are `repo_understanding_agent`, responsible for comprehensively analyzing a GitHub repository using only the available tools. Follow this workflow **(DO NOT re-start from the begin, please go ahead from the last step you were processing, e.g.retrieve_github_file_content)**:

                1. Use `wait_for_mentions(timeoutMs=30000)` to wait for instructions from other agents.**
                2. When a mention is received, record the `threadId` and `senderId`.
                3. Check if the message contains a `repo` name, `owner`, and a target `branch`.
                4. Call `get_all_github_files(repo_name = ..., branch = ...)` to list all files.
                5. Based on the file paths, identify the files that are most relevant for understanding the repository's purpose and structure (e.g., `README.md`, `setup.py`, main source code files, configuration files, test files, etc.).
                6. For these selected files, use `retrieve_github_file_content(repo_name = ..., file_path = ..., branch = ...)` to retrieve their content, **please only open one file each time**
                -Analyze the decoded content to extract:
                    - The overall project purpose and main functionality.
                    - The primary components/modules and their roles.
                    - How to use or run the project (if available).
                    - Any noteworthy implementation details or structure.
                7. Once you have gained sufficient understanding of the repository, summarize your findings clearly and concisely.
                8. Use `send_message(senderId=..., mentions=[senderId], threadId=..., content="your summary")` to reply to the sender with your analysis.
                9. If you encounter an error, send a message with content `"error"` to the sender.
                10. Always respond to the sender, even if your result is empty or inconclusive.
                11. Wait 2 seconds and repeat from step 1.

                **Note: Each ten time you call any tool, you need to call `recall_system_message()` to recall system message**
                
                Tools: {get_tools_description(tools)}, Tool: recall_system_message  
                Schema: (
                "system_message": (
                    "title": "System Message",
                    "type": "string"
                )
                )"""

                @tool
                def recall_system_message() -> str:
                    """
                    Recall (output) the current agent's system message (prompt).

                    Returns:
                        str: The original system message, for agent to re-read and self-remind.
                    """
                    return AGENT_SYSTEM_PROMPT

                tools += [recall_system_message]

                logger.info(f"Tools Description:\n{get_tools_description(tools)}")

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
