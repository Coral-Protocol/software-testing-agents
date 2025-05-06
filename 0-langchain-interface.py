import asyncio
import os
import json
import logging
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain.tools import Tool
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
            1. Call list_agents (includeDetails: True) to check registration of 'user_interaction_agent'. If not registered, call register_agent (agentId: 'user_interaction_agent', agentName: 'User Interaction Agent', description: 'Handles user instructions and coordinates testing tasks.'). Retry once on failure, otherwise send a message: 'Error checking agent registration.'
            2. Create a thread using create_thread (threadName: 'User Interaction Thread', creatorId: 'user_interaction_agent', participantIds: ['user_interaction_agent']). Store threadId. Retry once on failure, otherwise stop and report: 'Error creating thread.'
            3. Send message: 'I am ready to receive testing instructions.' Retry once on failure, otherwise send: 'Error sending readiness message.'

            **Loop**:
            1. Use ask_human to ask: 'What instructions do you have for me?'
            2. If message contains 'unit test', 'PR', or 'diff', proceed as follows:
            - Check if 'codediff_review_agent' is registered. If so, call add_participant to add it to the thread. If failed, send: 'Error adding Code Diff Review Agent.'
            - Check if 'unit_test_runner_agent' is registered. If so, call add_participant. If failed, send: 'Error adding Unit Test Runner Agent.'
            - Send message to codediff_review_agent: 'Analyze the diff between ./user_code/calculator.py and ./user_code/calculator_PR.py.' Mention the agent.
            - **call wait_for_mentions up to 10 times (agentId: 'user_interaction_agent', timeoutMs: 8000) or until messages are received.** Parse the diff result and extract function names affected (e.g., test_multiply).
            - Send message: 'Please run unit test: [test_name]' to unit_test_runner_agent. Mention the agent.
            - **call wait_for_mentions up to 10 times (agentId: 'user_interaction_agent', timeoutMs: 8000) or until messages are received.**
            - Format results as 'Test result: [status]\nOutput:\n[output]'.
            - Send the result to the thread via send_message (content: [formatted results], mentions: []). If send_message fails, retry once. If it fails again, send: 'Error sending test results.'
            - Send a confirmation message to the thread with send_message (content: 'Task completed.', mentions: []). 
              If send_message fails, retry once. If it fails again, send: 'Error sending task completion message.'
            - Repeat by returning to step 1 (ask_human).

            **For any other instruction**:
            - If message is 'list agents' or similar, call list_agents and report results.
            - If message is 'close thread', close and re-create thread.
            - If empty input, reply with: 'No valid instructions received.'
            

            **Notes**:
            - Cache agent list after list_agents.
            - Track threadId across loop iterations.
            - Use only tools: {tools_description}"""
        ),
        ("placeholder", "{agent_scratchpad}")
    ])

    model = ChatOpenAI(
        model="gpt-4o-mini",
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=0.3,
        max_tokens=4096
    )

    agent = create_tool_calling_agent(model, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=True)

async def main():
    max_retries = 3
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
                logger.info("Retrying in 5 seconds...")
                await asyncio.sleep(5)
                continue
            else:
                logger.error("Max retries reached. Exiting.")
                raise
        except Exception as e:
            logger.error(f"Unexpected error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                logger.info("Retrying in 5 seconds...")
                await asyncio.sleep(5)
                continue
            else:
                logger.error("Max retries reached. Exiting.")
                raise

if __name__ == "__main__":
    asyncio.run(main())