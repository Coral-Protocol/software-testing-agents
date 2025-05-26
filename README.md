# Repo Understanding Agent

This project provides an autonomous agent that **comprehensively analyzes and summarizes any GitHub repository**. It uses only two tools—`get_all_github_files`, and `retrieve_github_file_content`—to extract key file contents and deliver concise, high-level insights. Specifically, we customized a **HeadSummaryMemory** class for the Repo Understanding Agent to solve the long context issue.

---

## How It Works

The agent follows this general workflow:

1. **Receive instructions** about a target repository, branch, and (optionally) a question or focus.
2. **List all files** in the specified repository and branch using `get_all_github_files`.
3. **Select important files** (e.g., `README.md`, `setup.py`, core modules, configs) for deeper analysis.
4. **Retrieve file contents** one at a time with `retrieve_github_file_content`.
5. **Analyze content** to understand:

   * The project's overall purpose and functionality
   * Key components/modules and their roles
   * How to use, run, or install the project (if documented)
   * Noteworthy implementation details or architecture
6. **Summarize findings** and send the result back to the requester.

---

## How to Start the System

1. **Start the Coral Server**
   Please refer to the official documentation for setup and usage instructions:
   [Coral Server GitHub](https://github.com/Coral-Protocol/coral-server)

2. **Start the Agents**
   Open two terminals, and run the following commands separately:

   ```
   python 0-langchain-interface.py
   ```

   ```
   python 1-langchain-RepoUnderstandingAgent.py
   ```

   > Each agent runs in its own terminal and communicates via the Coral server.

---

## Example Prompts

Ask the agent for a comprehensive repo summary or instructions such as:

```
Please give me a comprehensive instruction of Coral-Protocol/coraliser.
```

or

```
Please give me a comprehensive instruction of the master branch of Coral-Protocol/coral-server.
```

or

```
Please give me a comprehensive instruction of the master branch of camel-ai/camel.
```

The agent will respond with a structured summary, covering project purpose, major modules, and how to use the codebase.

---
