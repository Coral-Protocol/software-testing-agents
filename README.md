# Software Testing Advisor Agents

This project provides a **multi-agent system for automated software testing advice**. The system is composed of three specialized agents working collaboratively:

* **InterfaceAgent:** Interacts with the user, collects PR information, and coordinates the workflow.
* **CodeDiffReviewAgent:** Analyzes the pull request to identify all changed files.
* **RepoUnitTestAdvisorAgent:** Evaluates whether the unit tests for the changed files comprehensively cover all necessary cases and provides actionable improvement suggestions.

---

## How It Works

The agents follow this workflow:

1. **Receive user instruction** (e.g., a PR has been created or updated).
2. **CodeDiffReviewAgent** analyzes the PR to **identify all files that have been changed**.
3. For each changed file, **RepoUnitTestAdvisorAgent**:

   * Locates related unit tests.
   * Analyzes whether existing tests **cover all required functionalities, edge cases, and error handling** for the modified code.
   * Provides detailed feedback, including any **additional test cases that should be added**.
4. **InterfaceAgent** aggregates the findings and **delivers clear recommendations** back to the user.

---

## Example Usage

You can interact with the system using natural language instructions, such as:

```
I created a new branch, `new-semantic-scholar-toolkit`, in the repository `renxinxing123/camel-software-testing` and opened a new pull request (#3). For the changed files, could you please help me check whether the according unit tests fully cover all necessary cases? Are there any additional tests that should be added?
```

The agent system will analyze your pull request, review the associated unit tests for every changed file, and report back with coverage evaluation and suggestions for further improvement.

---
