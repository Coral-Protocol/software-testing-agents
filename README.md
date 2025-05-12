# Software Testing Agents with LangChain

This example demonstrates a minimal multi-agent software testing system built using LangChain and the Coral Protocol. Agents collaborate to fetch, analyze, and test pull requests (PRs) against existing unit tests.

The current use case demonstrates a simple example of testing a pull request (PR) made to this repository: [https://github.com/renxinxing123/software-testing-code](https://github.com/renxinxing123/software-testing-code). It is designed as a minimal working demo and can be extended to support more complex codebases.

---

## Overview of Agents

The system consists of four cooperating agents, each with a specific responsibility:

* **Interface Agent**
  Accepts user instructions, manages the workflow, and coordinates other agents.

* **GitCloneAgent**
  Clones the GitHub repository and checks out the specific pull request branch.
  → Uses the `checkout_github_pr` tool to clone the repo and check out the PR branch using `git` commands.

* **CodeDiffReviewAgent**
  Analyzes the PR diff, identifies the changed function, maps it to the corresponding test function, and locates the test file path.
  → Uses the `get_pr_code_changes` tool built on top of the GitHub API via `PyGithub` to fetch the code diffs of the PR.

* **UnitTestRunnerAgent**
  Runs the specified unit test using `pytest` and returns structured test results.
  → Uses three tools:

  * `list_project_files` to enumerate all project files,
  * `read_project_files` to read test source code,
  * `run_test` to execute the selected test with `pytest` and capture structured output.

---

## Prerequisites

Before running this project, clone the [Coral MCP server](https://github.com/Coral-Protocol/coral-server):

```bash
git clone https://github.com/Coral-Protocol/coral-server.git
```

Make sure you have:

* Python 3.9 or above
* A valid `OPENAI_API_KEY` exported in your environment
* A valid `GITHUB_ACCESS_TOKEN` exported in your environment

---

## Running the Example

### 1. Install Dependencies

```bash
pip install langchain-mcp-adapters langchain-openai worldnewsapi langchain langchain-core PyGithub
```

---

### 2. Start the MCP Server

Navigate to the `coral-server` directory and run:

```bash
./gradlew run
```

Note: Gradle may appear to stall at 83%, but the server is running. Check terminal logs to confirm.

---

### 3. Launch Agents (in four separate terminals)

```bash
# Terminal 1: Interface Agent
python 0-langchain-interface.py
```

```bash
# Terminal 2: GitClone Agent
python 1-langchain-GitCloneAgent.py
```

```bash
# Terminal 3: CodeDiffReview Agent
python 2-langchain-CodeDiffReviewAgent.py
```

```bash
# Terminal 4: UnitTestRunner Agent
python 3-langchain-UnitTestRunnerAgent.py
```

---

### 4. Interact with the System

Once all agents are running, interact with the Interface Agent via standard input.

Example instructions:

```
Please execute the unit test for the '6' PR in repo 'renxinxing123/software-testing-code'.
```

In this example, since **all functions in the PR were modified**, the Software Testing Agents intelligently executed **all available unit tests** to ensure full coverage.

```
Please execute the unit test for the '7' PR in repo 'renxinxing123/software-testing-code'.
```

In contrast, this PR only modified a **subset of functions**, so the UnitTestRunnerAgent **selectively executed only the relevant unit tests**. At the end of execution, it also **clearly reports which tests were skipped**, alerting users in case any critical tests were unintentionally omitted.

---


## Get Involved

This is an early-stage prototype. Feedback and contributions are welcome.

Discord: [https://discord.gg/cDzGHnzkwD](https://discord.gg/cDzGHnzkwD)

---



