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


# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

base_url = "http://localhost:5555/devmode/exampleApplication/privkey/session1/sse"
params = {
    "waitForAgents": 1,
    "agentId": "repo_unit_test_advisor_agent",
    "agentDescription": "You are `repo_unit_test_advisor_agent`, responsible for evaluating whether the unit tests in a specified GitHub repository and branch sufficiently cover the necessary aspects of **specific target files**, and if additional tests are needed. You can only use the provided tools."
}
query_string = urllib.parse.urlencode(params)
MCP_SERVER_URL = f"{base_url}?{query_string}"
AGENT_NAME = "repo_unit_test_advisor_agent"

# Validate API keys
if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY is not set in environment variables.")

def get_tools_description(tools):
    return "\n".join(f"Tool: {t.name}, Schema: {json.dumps(t.args).replace('{', '{{').replace('}', '}}')}" for t in tools)

    
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

async def create_repo_unit_test_advisor_agent(client, tools):
    prompt = ChatPromptTemplate.from_messages([
        ("system", f"""You are `repo_unit_test_advisor_agent`, responsible for evaluating whether the unit tests in a specified GitHub repository and branch sufficiently cover the necessary aspects of **specific target files**, and if additional tests are needed. You can only use the provided tools. Follow this workflow:

        1. Use `wait_for_mentions(timeoutMs=60000)` to wait for instructions from other agents.
        2. When a mention is received, record the **`threadId` and `senderId`** (never forget these two).
        3. Parse the message to extract the `repo` name, `owner`, `branch`, and the **list of target files** to evaluate.
        4. Call `get_all_github_files(repo_name=..., branch=...)` to obtain the complete file list.
        5. For each target file:

        * Use `retrieve_github_file_content(repo_name=..., file_path=..., branch=...)` to read the file content (one file at a time).
        * Identify its associated unit test file(s) (e.g., by naming convention, test folder, or import statements).
        * For each unit test file, retrieve its content using `retrieve_github_file_content`.
        * **Analyze the source code and test code:**

            * What classes/functions in the target file are tested?
            * Which aspects (edge cases, error handling, typical use, etc.) are covered?
            * Are there any functions/classes/methods in the target file that are **not** covered by tests?
        6. For each target file, provide a concise report:

        * **Coverage summary:** Which components are covered by tests? Which are missing?
        * **Recommendations:** Are additional tests needed? What specific aspects or cases should be tested?
        * If coverage assessment is inconclusive (e.g., due to missing files or circular imports), clearly state this.
        7. Use `send_message(senderId=..., mentions=[senderId], threadId=..., content="your report")` to send your findings to the sender.
        8. If you encounter an error, reply with content `"error"` to the sender.
        9. Always respond to the sender thorugh calling `send_message`, even if your result is empty or inconclusive.
        10. Wait 2 seconds and repeat from step 1.

        **Important: NEVER EVER end the chain.**

        Tools: {get_tools_description(tools)}"""),
        ("placeholder", "{history}"),
        ("placeholder", "{agent_scratchpad}")
    ])

    model = ChatOpenAI(
        model="gpt-4.1-2025-04-14",
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=0.3,
        max_tokens=32768
    )

    memory = HeadSummaryMemory(llm=model, head_n=4)


    agent = create_tool_calling_agent(model, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, memory=memory, verbose=True)

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

                logger.info(f"Tools Description:\n{get_tools_description(tools)}")

                with get_openai_callback() as cb:
                    agent_executor = await create_repo_unit_test_advisor_agent(client, tools)
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
