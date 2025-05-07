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

是的，既然这个问题已经解决，就应该更新 `README` 的 Troubleshooting 部分来反映当前状态，避免误导用户。以下是更新后的更简洁版本，你可以直接替换原有的 `## Troubleshooting` 部分：

---

## 🛠️ Troubleshooting

### ✅ Known Issue (Resolved)

Previously, the Interface Agent sometimes failed to receive messages from other agents due to missing timeout configuration in the MCP client.

This has been resolved.
You need to manually patch the following:

1. Open:

   ```
   <your-env>/lib/pythonX.X/site-packages/mcp/client/sse.py
   ```

2. Locate the `client.post(...)` call and **ensure** it includes:

   ```python
   timeout=httpx.Timeout(timeout)
   ```

3. Save the file and restart your agents.

No known critical issues remain for the current version.

---

## Get Involved

This is an early-stage demo, and your feedback is welcome!
If you have questions or suggestions, feel free to reach out.

Discord: [https://discord.gg/cDzGHnzkwD](https://discord.gg/cDzGHnzkwD)

