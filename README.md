# LSH (LLM Shell)

**LSH** is a Python-based shell wrapper that integrates a Local Large Language Model (LLM) via Ollama. It behaves like a normal shell for standard operations but acts as an intelligent agent when commands fail.

If a command crashes (non-zero exit code), LSH captures the output, sends it to the LLM, and suggests a fix automatically.

## Features

*   **Native Shell Experience**: Uses `pty` (pseudo-terminals) to ensure colors, formatting, and real-time output streaming work exactly like Bash/Zsh.
*   **Smart Error Recovery**: Automatically detects non-zero exit codes and consults the LLM.
*   **Interactive Tool Bypass**: Intelligently detects tools like `vim`, `htop`, `ssh`, and `k9s`. It runs these directly without output capturing to ensure full UI compatibility.
*   **Agent Mode**: Option to automatically execute the LLM's suggested fix (`AGENT_MODE = True`).
*   **Privacy First**: Runs entirely locally using Ollama. No shell history or data is sent to the cloud.

## Prerequisites

1.  **Python 3.8+**
2.  **Ollama**: You need [Ollama](https://ollama.com/) installed and running locally.
3.  **An LLM Model**: You need to pull a model (e.g., `gemma`, `llama3`, `mistral`).

## Installation

1.  **Clone or save the script**:
    Save the code as `lsh.py`.

2.  **Install Python Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Prepare Ollama**:
    Make sure Ollama is running and you have the model specified in the script.
    ```bash
    # Start Ollama server
    ollama serve
    
    # In a new terminal, pull the model (matches LLM_MODEL in lsh.py)
    ollama pull gemma3n:latest
    ```

## Configuration

Open `lsh.py` in your text editor to tweak the settings at the top of the file:

```python
LLM_MODEL  = "gemma3n:latest"    # The specific model name you pulled via Ollama.
```

### Interactive Exclusion List
Modify `IGNORE_LIST` in `lsh.py` to add more tools that should bypass the LLM capture logic (e.g., custom TUI apps):

```python
IGNORE_LIST = {
    "vi", "vim", "nvim", "htop", "top", "ssh", "tmux", ...
}
```

## Usage

Start the shell:

```bash
python3 lsh.py
```

or in agent mode
```bash
python3 lsh.py --agent
```

customize llm
```bash
python3 lsh.py --llm gpt-oss:120b
```

### 1. Normal Commands
Works exactly like your standard terminal.
```bash
lsh:/home/user$ ls -la
lsh:/home/user$ echo "Hello World"
```

### 2. Automatic Fixes (The Magic)
If you make a typo or run a command incorrectly:

```bash
lsh:/home/user$ gi status
# Output: lsh: command not found: gi

Analyzing failure with gemma3n:latest... Done.

Suggested Fix: git status
Run this command? [y/N] y
# (Runs 'git status' successfully)
```

### 3. Complex Errors
If a compilation fails or a python script crashes:

```bash
lsh:/home/user$ python3 my_broken_script.py
# Output: Traceback... NameError: name 'pd' is not defined...

Analyzing failure... Done.

Suggested Fix: pip install pandas && python3 my_broken_script.py
Run this command? [y/N]
```

### 4. Use natural language to run shell command
If you dont know what command to use, just ask shell how to run it.

```bash
lsh:/home/user$ List all the text file
# Output: List: all the text file...

Analyzing failure with gemma3n:latest... Done

Suggested Fix: ls *.txt
Run this command? [y/N]
```

## How It Works

1.  **Input Parsing**: LSH reads your input and checks if the command is in the `IGNORE_LIST`.
2.  **PTY Streaming**:
    *   If ignored (e.g., `vim`), it hands over control via `subprocess.run`.
    *   If normal (e.g., `ls`, `grep`), it creates a master/slave pseudo-terminal pair. This allows `lsh` to read output bytes *as they are generated* (preserving colors and animations) while simultaneously storing them in a buffer.
3.  **Exit Code Check**: Upon completion, if the exit code is `0`, the buffer is discarded.
4.  **LLM Context**: If the exit code is `!= 0`, the buffered output is sent to the local Ollama instance with a prompt to fix the issue.

## Limitations

*   **Aliases**: Because this runs in Python, aliases defined in your `.bashrc` or `.zshrc` might not be available unless you explicitly source them or run the shell in a specific interactive mode (though basic path executables work fine).
*   **Environment Variables**: `export` commands run inside `lsh` only persist for the current session.

## License

MIT License - Feel free to modify and distribute.
