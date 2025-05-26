# Software Testing Advisor Agents

This project provides a **multi-agent system for automated software testing advice**. The system consists of three collaborative agents, each specializing in a key aspect of the review process:

* **InterfaceAgent:** Interacts with the user, collects pull request (PR) information, and coordinates the overall workflow.
* **CodeDiffReviewAgent:** Analyzes the pull request to identify all changed files.
* **RepoUnitTestAdvisorAgent:** Evaluates whether the unit tests for the changed files comprehensively cover all necessary cases and provides actionable suggestions for improvement.

---

## How It Works

The agents operate in the following workflow:

1. **Receive user instruction:** For example, notification that a new or updated PR has been created.
2. **CodeDiffReviewAgent** examines the PR to **identify all files that have been changed**.
3. For each changed file, the **RepoUnitTestAdvisorAgent**:

   * Locates associated unit tests.
   * Analyzes whether current tests **cover all required functionalities, edge cases, and error handling** for the modified code.
   * Provides detailed feedback, including **additional test cases that should be added** if coverage is insufficient.
4. **InterfaceAgent** aggregates the findings and **delivers clear, actionable recommendations** to the user.

---

## How to Start the System

1. **Start the Coral Server**
   Please refer to the official documentation for setup and usage instructions:
   [Coral Server GitHub](https://github.com/Coral-Protocol/coral-server)

2. **Start the Agents**
   Open three terminals, and in each one, run the following commands separately:

   ```
   python 0-langchain-interface.py
   ```

   ```
   python 2-langchain-CodeDiffReviewAgent.py
   ```

   ```
   python 3-langchain-RepoUnitTestAdvisorAgent.py
   ```

   > Each agent runs in its own terminal and communicates via the Coral server.

---

## Example Usage

You can interact with the system using natural language instructions, such as:

```
I created a new branch, `new-semantic-scholar-toolkit`, in the repository `renxinxing123/camel-software-testing` and opened a new pull request (#3). For the changed files, could you please help me check whether the corresponding unit tests fully cover all necessary cases? Are there any additional tests that should be added?
```

The agent system will automatically analyze your pull request, review unit test coverage for every changed file, and report back with evaluation results and suggestions for improvement.

---


