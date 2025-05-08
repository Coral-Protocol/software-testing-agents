import asyncio
import os
import json
import logging
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain.tools import Tool
from langchain_ollama.chat_models import ChatOllama
from dotenv import load_dotenv
from anyio import ClosedResourceError
import urllib.parse

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

base_url = "http://localhost:5555/devmode/exampleApplication/privkey/session1/sse"
params = {
    "waitForAgents": 1,
    "agentId": "user_interaction_agent",
    "agentDescription": "You are user_interaction_agent, handling user instructions and coordinating testing tasks across agents"
}
query_string = urllib.parse.urlencode(params)
MCP_SERVER_URL = f"{base_url}?{query_string}"
AGENT_NAME = "user_interaction_agent"

def get_tools_description(tools):
    return "\n".join(
        f"Tool: {tool.name}, Schema: {json.dumps(tool.args).replace('{', '{{').replace('}', '}}')}"
        for tool in tools
    )

async def ask_human_tool(question: str) -> str:
    print(f"Agent asks: {question}")
    return input("Your response: ")

async def create_interface_agent(client, tools):
    tools_description = get_tools_description(tools)
    
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            f"""You are user_interaction_agent, handling user instructions and coordinating testing tasks across agents.

            **Initialization**:
            1. Call list_agents (includeDetails: True) to check registration of 'user_interaction_agent'.  
            If not registered, call:  
            register_agent(agentId: 'user_interaction_agent', agentName: 'User Interaction Agent', description: 'Handles user instructions and coordinates testing tasks.')  
            Retry once on failure. If it fails again, send a message to the thread: 'Error checking agent registration.'

            2. Create a thread using create_thread (threadName: 'User Interaction Thread', creatorId: 'user_interaction_agent', participantIds: ['user_interaction_agent']).  
            Store threadId. Retry once on failure. If it fails again, stop and report: 'Error creating thread.'

            3. Send message: 'I am ready to receive testing instructions.' Retry once. If failed again, send: 'Error sending readiness message.'

            ---

            **Loop (STRICTLY follow each step, NEVER skip any step)**:

            1. Use ask_human to ask:  
            'Please tell me the GitHub repo (e.g., owner/repo) and the PR number to test.'

            2. After receiving the human reply, extract:
            - `repo_name` (e.g., 'octocat/calculator')
            - `pr_number` (e.g., 42)

            3. Check and add the following agents if needed:
            - 'gitclone_agent' → if registered, call add_participant. On failure, send: 'Error adding Git Clone Agent.'
            - 'codediff_review_agent' → call add_participant. On failure, send: 'Error adding Code Diff Review Agent.'
            - 'unit_test_runner_agent' → call add_participant. On failure, send: 'Error adding Unit Test Runner Agent.'

            4. Send message to `gitclone_agent`:  
            "Checkout PR #[pr_number] from '[repo_name]'".  
            Use send_message (senderId: 'user_interaction_agent', mentions: ['gitclone_agent']).

            5. KEEP calling wait_for_mentions (agentId: 'user_interaction_agent', timeoutMs: 30000) until messages are received.  
            - If no messages after 3 attempts, send: 'No response from gitclone_agent.'  
            - Extract the `Local path: [repo_path]` from the response. Store as `project_root`.

            6. Send message to `codediff_review_agent`:  
            "Analyze PR #[pr_number] from '[repo_name]'".  
            Use send_message (senderId: 'user_interaction_agent', mentions: ['codediff_review_agent']).

            7. KEEP calling wait_for_mentions (agentId: 'user_interaction_agent', timeoutMs: 30000) until messages are received.  
            - If no messages after 3 attempts, send: 'No response from codediff_review_agent.'  
            - Extract from the response:
                - `test_name` (e.g., test_multiply)
                - `relative_test_path` (e.g., tests/test_calculator.py)

            8. Send message to `unit_test_runner_agent`:  
            "Please run unit test '[test_name]' located in '[relative_test_path]' under project root '[project_root]'".  
            Use send_message (senderId: 'user_interaction_agent', mentions: ['unit_test_runner_agent']).

            9. KEEP calling wait_for_mentions (agentId: 'user_interaction_agent', timeoutMs: 30000) until messages are received.  
            - If no messages after 3 attempts, send: 'No response from unit_test_runner_agent.'  
            - Extract:
                - `status` (e.g., Test passed/Test failed)
                - `output` (full pytest output)

            10. Format result as:
                ```
                Test result: [status]
                Output:
                [output]
                ```

            11. Send the result to the thread using send_message (content: [formatted results], mentions: []).  
                Retry once. If it fails again, send: 'Error sending test results.'

            12. Send a confirmation message using send_message (content: 'Task completed.', mentions: []).  
                Retry once. If it fails again, send: 'Error sending task completion message.'

            13. Return to step 1.

            ---

            **For any other instruction**:
            - If message is 'list agents' or similar, call list_agents and report results.
            - If message is 'close thread', close the current thread and re-create a new one. Continue interaction in the new thread.
            - If input is empty or invalid, reply: 'No valid instructions received.'

            ---

            **Notes**:
            - Cache agent list after list_agents and reuse across loop iterations.
            - Track threadId persistently.
            - Use only tools: {tools_description}"""),
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
    max_retries = 5
    retry_delay = 5  # seconds
    for attempt in range(max_retries):
        try:
            async with MultiServerMCPClient(
                connections={
                    "coral": {
                        "transport": "sse",
                        "url": MCP_SERVER_URL,
                        "timeout": 30,
                        "sse_read_timeout": 60,  # Reduced timeout
                    }
                }
            ) as client:
                logger.info(f"Connected to MCP server at {MCP_SERVER_URL}")
                tools = client.get_tools() + [Tool(
                    name="ask_human",
                    func=None,
                    coroutine=ask_human_tool,
                    description="Ask the user a question and wait for a response."
                )]
                logger.info(f"Tools Description:\n{get_tools_description(tools)}")
                await (await create_interface_agent(client, tools)).ainvoke({})
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