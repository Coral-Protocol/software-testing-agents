# Software Testing Agents with CAMEL

In this example, we implement a minimal multi-agent software testing system using LangChain, where agents collaboratively test pull request (PR) code against existing unit tests.

The use case is currently in an early stage and focuses on local testing for a simple calculator. It involves three agents working together:

* **Interface Agent**: Accepts user instructions and coordinates with other agents.
* **CodeDiffReviewAgent**: Analyzes code differences between the original and PR version, and identifies which functions have changed.
* **UnitTestRunnerAgent**: Runs the appropriate unit tests based on the changed parts identified by the CodeDiffReviewAgent.

---

## Prerequisite

Before running this example, make sure to **clone the Coral MCP server**:

```bash
git clone https://github.com/Coral-Protocol/coral-server.git
```

---

## Running the Example

### 1. Install the dependencies

Make sure you have Python 3.9+ installed. Then run:

```bash
pip install langchain-mcp-adapters langchain-openai worldnewsapi langchain langchain-core
```
---

### 2. Start the MCP Server

If you haven't already, clone the MCP repo and navigate to the project root:

```bash
./gradlew run
```

> ⚠️ Note: Gradle may appear to hang at "83%", but the server is actually running. Check your terminal logs to confirm.

---

### 3. Run the Agents

Make sure you have your `OPENAI_API_KEY` exported in your terminal environment.
In **three separate terminals**, run the following:

```bash
# Terminal 1
python 0-langchain-interface.py
```

```bash
# Terminal 2
python 1-langchain-UnitTestRunnerAgent.py
```

```bash
# Terminal 3
python 2-langchain-CodeDiffReviewAgent.py
```

---

### 4. Interact with the Agents

Once all agents are running, you can send a query via STDIN to the Interface Agent terminal.

Try something like:

```
Please execute the unit test for the PR code.
```

The Interface Agent will coordinate with the CodeDiffReviewAgent to determine the code changes, and then with the UnitTestRunnerAgent to execute relevant unit tests.

---

## Troubleshooting

* The system is currently **unstable**:
  Sometimes the Interface Agent **fails to receive messages** from other agents, even though those agents can receive messages from it.

* Sample Error Logs:

  ```text
  No new messages received within the timeout period
  Invoking: `wait_for_mentions` with `{'timeoutMs': 8000}`

  ClosedResourceError on attempt 1: 
  Retrying in 5 seconds...
  ```

* Potential Cause:
  Although the `prompt` includes `**call wait_for_mentions up to 10 times (agentId: 'user_interaction_agent', timeoutMs: 8000)**`, it seems the system does not always respect this logic or may hit a network or session registration issue.

---

## Get Involved

This is an early-stage demo, and your feedback is welcome!
If you have questions or suggestions, feel free to reach out.

Discord: [https://discord.gg/cDzGHnzkwD](https://discord.gg/cDzGHnzkwD)

