import os
import sys
import subprocess
import pty
import select
import re
import shlex
from langchain_community.llms import Ollama
import warnings
warnings.filterwarnings("ignore")

# --- Configuration ---
AGENT_MODE = False                # set True -> auto-run the suggested fix
LLM_MODEL  = "gemma3n:latest"           # Change to your model (e.g., llama3, mistral)

# Tools that take over the full screen or require raw TTY access.
# We do NOT capture output for these to prevent UI glitches.
IGNORE_LIST = {
    "vi", "vim", "nvim", "nano", "emacs",
    "htop", "top", "nvtop", "btop", "k9s",
    "less", "more", "man", "ssh", "tmux", "screen"
}

# --- LLM Setup ---
# Optional: Set env vars if not set globally
os.environ.setdefault('OLLAMA_HOST', 'http://localhost:11434')

print(f"Connecting to LLM ({LLM_MODEL})...")
try:
    llm = Ollama(model=LLM_MODEL)
except Exception as e:
    print(f"Error initializing Ollama: {e}")
    sys.exit(1)

def extract_code_block(text: str) -> str:
    """Extracts the content inside ```bash ... ``` or ``` ... ```."""
    pattern = r"```(?:bash|sh)?\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        return matches[0].strip()
    return text.strip() # Fallback: return raw text if no code block

def ask_llm_for_fix(cmd: str, full_output: str, code: int) -> str:
    """Consults the LLM for a fix."""
    # Truncate output if it's massive to save context window
    truncated_out = full_output[-2000:] if len(full_output) > 2000 else full_output
    
    prompt = (
        f"You are a helpful shell assistant.\n"
        f"The user ran this command and it failed:\n"
        f"Command: `{cmd}`\n"
        f"Exit Code: {code}\n"
        f"Output/Error (last 1000 chars):\n```\n{truncated_out}\n```\n\n"
        f"Provide ONLY the corrected shell command inside a ```bash``` code block. "
        f"Do not explain unless necessary. If the command was a typo, fix the typo."
    )
    
    try:
        print(f"\nAnalyzing failure with {LLM_MODEL}...", end="", flush=True)
        response = llm.invoke(prompt)
        print(" Done.")
        return response
    except Exception as e:
        return f"LLM Error: {e}"

def run_interactive(cmd_list):
    """Runs interactive tools directly (std streams connected)."""
    try:
        subprocess.run(cmd_list)
        return 0, "" # We don't capture output from interactive tools
    except FileNotFoundError:
        print(f"lsh: command not found: {cmd_list[0]}")
        return 127, ""
    except Exception as e:
        print(f"lsh: execution error: {e}")
        return 1, ""

def run_capturing(cmd_str):
    """
    Runs command in a PTY (pseudo-terminal).
    Streams output to user in real-time AND captures it into a buffer.
    """
    master, slave = pty.openpty()
    
    # Start the process using the user's default shell (bash/zsh/sh)
    # This supports pipes (|) and redirects (>) naturally.
    p = subprocess.Popen(
        cmd_str, 
        shell=True, 
        stdout=slave, 
        stderr=slave, 
        stdin=slave,
        close_fds=True
    )
    
    os.close(slave) # Close slave in parent, otherwise we hang reading

    captured_output = bytearray()
    
    try:
        while True:
            # Check if data is available to read from master
            r, _, _ = select.select([master], [], [], 0.1)
            
            if master in r:
                data = os.read(master, 1024)
                if not data:
                    break # EOF
                
                # 1. Show user immediately (Raw byte stream)
                os.write(sys.stdout.fileno(), data)
                
                # 2. Buffer for LLM
                captured_output.extend(data)
            
            # Check if process is dead
            if p.poll() is not None:
                # Read any remaining data
                rest = os.read(master, 4096) # Non-blocking try
                if rest:
                    os.write(sys.stdout.fileno(), rest)
                    captured_output.extend(rest)
                break
    except OSError:
        pass
    finally:
        os.close(master)

    p.wait()
    output_str = captured_output.decode("utf-8", errors="replace")
    return p.returncode, output_str

# --- Main Loop ---
def main():
    print(f"Welcome to LSH (LLM Shell). Type 'exit' to quit.")
    
    while True:
        try:
            # Get current directory for prompt
            cwd = os.getcwd()
            # Pretty prompt
            prompt = f"\033[1;32mlsh\033[0m:\033[1;34m{cwd}\033[0m$ "
            
            user_input = input(prompt).strip()
            
            if not user_input:
                continue

            if user_input in ["exit", "quit"]:
                break

            # Tokenize to check the first command
            try:
                tokens = shlex.split(user_input)
                if not tokens: continue
                base_cmd = tokens[0]
            except ValueError:
                # Handle unclosed quotes, etc.
                base_cmd = user_input.split()[0]

            # 1. Handle Built-ins
            if base_cmd == "cd":
                try:
                    target = tokens[1] if len(tokens) > 1 else os.path.expanduser("~")
                    os.chdir(target)
                except Exception as e:
                    print(f"cd: {e}")
                continue

            # 2. Check for Interactive/Exclude list
            if base_cmd in IGNORE_LIST:
                exit_code, _ = run_interactive(tokens)
                # We don't use LLM for vim/htop failures usually
                continue

            # 3. Run Standard Command (Capturing)
            exit_code, full_output = run_capturing(user_input)

            # 4. Error Handling Logic
            if exit_code != 0:
                response = ask_llm_for_fix(user_input, full_output, exit_code)
                
                fixed_cmd = extract_code_block(response)
                
                print(f"\n\033[1;33mSuggested Fix:\033[0m {fixed_cmd}")
                
                if AGENT_MODE:
                    print(f"\033[1;35mAgent Mode executing fix...\033[0m")
                    # Recursive call? Or just run once? Let's run once to avoid infinite loops.
                    run_capturing(fixed_cmd)
                else:
                    # Interactive Mode
                    confirm = input("Run this command? [y/N] ")
                    if confirm.lower() == 'y':
                        run_capturing(fixed_cmd)

        except KeyboardInterrupt:
            print("\n")
            continue
        except EOFError:
            break

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Use LLM to fix shell commands.")
    parser.add_argument("--agent", default=False, action="store_true", help="Use agent mode.")

    args = parser.parse_args()
    AGENT_MODE = args.agent
    main()
