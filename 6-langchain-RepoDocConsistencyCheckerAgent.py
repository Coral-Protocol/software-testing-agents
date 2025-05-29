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
from langchain.memory import ConversationSummaryMemory
from langchain_core.memory import BaseMemory
from dotenv import load_dotenv
from anyio import ClosedResourceError
import urllib.parse
import base64
import subprocess
from langchain_groq import ChatGroq


# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

base_url = "http://localhost:5555/devmode/exampleApplication/privkey/session1/sse"
params = {
    "waitForAgents": 7,
    "agentId": "repo_doc_consistency_checker_agent",
    "agentDescription": """I am `repo_doc_consistency_checker_agent`, responsible for evaluating whether the documentation (such as README, API docs, and configuration guides) in a specified GitHub repository and branch is up-to-date with respect to the **changes introduced in a given commit**. 
                           To proceed, you need to provide me with the `repo_name` (not local path), the `branch_name` (not PR number), and the changes introduced in a given commit"""
}
query_string = urllib.parse.urlencode(params)
MCP_SERVER_URL = f"{base_url}?{query_string}"
AGENT_NAME = "repo_doc_consistency_checker_agent"

# Validate API keys
if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY is not set in environment variables.")

def get_tools_description(tools):
    return "\n".join(f"Tool: {t.name}, Schema: {json.dumps(t.args).replace('{', '{{').replace('}', '}}')}" for t in tools)

    
@tool
def get_all_github_files_tool(repo_name: str, branch: str = "main") -> str:
    """
    Call the local get_all_github_files.py script and return all file paths in the specified repo and branch as a string.

    Args:
        repo_name (str): Full repository name in the format "owner/repo".
        branch (str): Branch name to retrieve files from.

    Returns:
        str: All file paths (one per line), or error message.
    """
    current_dir = os.path.abspath(os.path.dirname(__file__))
    script_path = os.path.join(current_dir, "get_all_github_files.py")

    result = subprocess.run(
        [
            "python",
            script_path,
            "--repo_name", repo_name,
            "--branch", branch
        ],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        return result.stdout
    else:
        return f"exit_code={result.returncode}\nstderr={result.stderr}"



@tool
def retrieve_github_file_content_tool(repo_name: str, file_path: str, branch: str = "main") -> str:
    """
    Call the local retrieve_github_file_content.py script and return the file content or error.

    Args:
        repo_name (str): Full repository name in the format "owner/repo".
        file_path (str): Path to the file in the repository.
        branch (str): Branch name to retrieve the file from.

    Returns:
        str: Script output (file content or error message).
    """
    # Get the absolute path of the current directory
    current_dir = os.path.abspath(os.path.dirname(__file__))
    script_path = os.path.join(current_dir, "retrieve_github_file_content.py")

    result = subprocess.run(
        [
            "python",
            script_path,
            "--repo_name", repo_name,
            "--file_path", file_path,
            "--branch", branch
        ],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        return result.stdout
    else:
        return f"exit_code={result.returncode}\nstderr={result.stderr}"


class HeadSummaryMemory(BaseMemory):
    def __init__(self, llm, head_n=3):
        super().__init__()
        self.head_n = head_n
        self._messages = []
        self.summary_memory = ConversationSummaryMemory(llm=llm)

    def save_context(self, inputs, outputs):
        user_msg = inputs.get("input") or next(iter(inputs.values()), "")
        ai_msg = outputs.get("output") or next(iter(outputs.values()), "")
        self._messages.append({"input": user_msg, "output": ai_msg})
        if len(self._messages) > self.head_n:
            self.summary_memory.save_context(inputs, outputs)

    def load_memory_variables(self, inputs):
        messages = []
        
        for i in range(min(self._head_n, len(self._messages))):
            msg = self._messages[i]
            messages.append(HumanMessage(content=msg['input']))
            messages.append(AIMessage(content=msg['output']))
        # summary
        if len(self._messages) > self._head_n:
            summary_var = self.summary_memory.load_memory_variables(inputs).get("history", [])
            if summary_var:
                
                if isinstance(summary_var, str):
                    messages.append(HumanMessage(content="[Earlier Summary]\n" + summary_var))
                elif isinstance(summary_var, list):
                    messages.extend(summary_var)
        return {"history": messages}

    def clear(self):
        self._messages.clear()
        self.summary_memory.clear()

    @property
    def memory_variables(self):
        return {"history"}
    
    @property
    def head_n(self):
        return self._head_n

    @head_n.setter
    def head_n(self, value):
        self._head_n = value

    @property
    def summary_memory(self):
        return self._summary_memory

    @summary_memory.setter
    def summary_memory(self, value):
        self._summary_memory = value

async def create_doc_consistency_checker_agent(client, tools):
    prompt = ChatPromptTemplate.from_messages([
        ("system", f"""You are `repo_doc_consistency_checker_agent`, responsible for evaluating whether the documentation in a specified GitHub repository and branch is up-to-date with respect to the **changes in a provided list of files**.
        You can only use the provided tools. Follow this workflow:

        1. Use `wait_for_mentions(timeoutMs=60000)` to wait for instructions from other agents.
        2. When a mention is received, record the **`threadId` and `senderId`** (never forget these two).
        3. Parse the message to extract the `repo_name`, `owner`, `branch`, and the **list of changed files**. Call `send_message(senderId=..., mentions=[senderId], threadId=...)` if any of these is missing.
        4. Call `get_all_github_files(repo_name=..., branch=...)` to get the list of all files in the repository for this branch.
        5. For each file in the list of changed files:
            * Use `retrieve_github_file_content_tool(repo_name=..., file_path=..., branch=...)` to read its content.
            * Identify which documentation files (such as `README.md`, or `.md`/`.rst`/`.txt` files in the same directory or in `docs/`) are most likely to be relevant to the change.
        6. For each relevant documentation file:
            * Use `retrieve_github_file_content_tool(repo_name=..., file_path=..., branch=...)` to read its content.
            * Check if the documentation is up-to-date with respect to the changes in the corresponding changed file (such as APIs, usage, dependencies, or configuration).
        7. Prepare a brief report for the sender:
            * List any documentation that is outdated or missing regarding the recent changes.
            * Provide recommendations on what should be updated.
            * If everything is already up to date, simply state that.
        8. Use `send_message(senderId=..., mentions=[senderId], threadId=..., content="your report")` to send your findings.
        9. If you encounter an error, reply with content `"error"` to the sender.
        10. Always respond to the sender through calling `send_message`, even if your result is empty or inconclusive.
        11. Wait 2 seconds and repeat from step 1.

        **Important: NEVER EVER end the chain.**

        Tools: {get_tools_description(tools)}"""),
        ("placeholder", "{history}"),
        ("placeholder", "{agent_scratchpad}")
    ])

    model = ChatOpenAI(
        model="gpt-4.1-2025-04-14",
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=0.3,
        max_tokens=32768,
        request_timeout=120,    
        max_retries=8           
    )

    '''model = ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0.3
    )'''

    memory = HeadSummaryMemory(llm=model, head_n=4)


    agent = create_tool_calling_agent(model, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, memory=memory, max_iterations=100, handle_parsing_errors = True, verbose=True)

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

                tools += [get_all_github_files_tool, retrieve_github_file_content_tool]

                logger.info(f"Tools Description:\n{get_tools_description(tools)}")

                with get_openai_callback() as cb:
                    agent_executor = await create_doc_consistency_checker_agent(client, tools)
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
