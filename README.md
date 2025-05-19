# Repo Understanding Agent

This project provides an autonomous agent that **comprehensively analyzes and summarizes any GitHub repository**. It uses only three tools—`get_all_github_files`, `retrieve_github_file_content`, and `recall_system_message`—to recursively explore a repository, extract key file contents, and deliver concise, high-level insights.

---

## How It Works

The agent follows this general workflow:

1. **Receive instructions** about a target repository, branch, and (optionally) a question or focus.
2. **List all files** in the specified repository and branch using `get_all_github_files`.
3. **Select important files** (e.g. `README.md`, `setup.py`, core modules, configs) for deeper analysis.
4. **Retrieve file contents** one at a time with `retrieve_github_file_content`.
5. **Analyze content** to understand:

   * The project's overall purpose and functionality
   * Key components/modules and their roles
   * How to use, run, or install the project (if documented)
   * Noteworthy implementation details or architecture
6. **Summarize findings** and send the result back to the requester.
7. Every 10 tool calls, the agent uses `recall_system_message` to re-read its own system prompt and stay on track.

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

The agent will respond with a structured summary, covering project purpose, major modules, and how to use the codebase.

---

## Tools Used

* **get\_all\_github\_files**: Lists all file paths in the repository (recursively).
* **retrieve\_github\_file\_content**: Reads and returns the decoded content of a specified file.
* **recall\_system\_message**: Outputs the agent’s current system prompt for self-reflection and context refresh (called after every 10 tool invocations).

---
