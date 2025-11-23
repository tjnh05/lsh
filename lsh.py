#!/usr/bin/env python3
import os
import sys
import subprocess
import pty
import select
import re
import shlex
from langchain_community.llms import Ollama
import warnings
import argparse

warnings.filterwarnings("ignore")

# Tools that take over the full screen or require raw TTY access
IGNORE_LIST = {
    "vi", "vim", "nvim", "nano", "emacs",
    "htop", "top", "nvtop", "btop", "k9s",
    "less", "more", "man", "ssh", "tmux", "screen"
}


def setup_llm(model_name: str, ollama_host: str):
    """Initialize and return the Ollama LLM instance with proper config."""
    print(f"Connecting to Ollama at {ollama_host} using model '{model_name}'...")
    
    # Set the host (supports both http://host:port and just host:port)
    os.environ['OLLAMA_HOST'] = ollama_host.rstrip('/')
    if not os.environ['OLLAMA_HOST'].startswith('http'):
        os.environ['OLLAMA_HOST'] = 'http://' + os.environ['OLLAMA_HOST']

    try:
        llm = Ollama(model=model_name)
        # Test connection with a tiny call
        llm.invoke("Say 'hi' in one word.")  # Warm up + verify
        print("LLM connected successfully!")
        return llm
    except Exception as e:
        print(f"Failed to initialize Ollama: {e}")
        print("Make sure ollama is running and the model is pulled: ollama pull {model_name}")
        sys.exit(1)


def extract_code_block(text: str) -> str:
    pattern = r"```(?:bash|sh)?\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    return matches[0].strip() if matches else text.strip()


def ask_llm_for_fix(llm, cmd: str, full_output: str, code: int) -> str:
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
        print(f"\nAnalyzing failure with {llm.model}...", end="", flush=True)
        response = llm.invoke(prompt)
        print(" Done.")
        return response
    except Exception as e:
        return f"LLM Error: {e}"


def run_interactive(cmd_list):
    try:
        subprocess.run(cmd_list)
        return 0, ""
    except FileNotFoundError:
        print(f"lsh: command not found: {cmd_list[0]}")
        return 127, ""
    except Exception as e:
        print(f"lsh: execution error: {e}")
        return 1, ""


def run_capturing(cmd_str):
    master, slave = pty.openpty()
    p = subprocess.Popen(
        cmd_str,
        shell=True,
        stdout=slave,
        stderr=slave,
        stdin=slave,
        close_fds=True
    )
    os.close(slave)

    captured_output = bytearray()
    
    try:
        while True:
            r, _, _ = select.select([master], [], [], 0.1)
            if master in r:
                data = os.read(master, 1024)
                if not data:
                    break
                os.write(sys.stdout.fileno(), data)
                captured_output.extend(data)
            
            if p.poll() is not None:
                rest = os.read(master, 4096)
                if rest:
                    os.write(sys.stdout.fileno(), rest)
                    captured_output.extend(rest)
                break
    except OSError:
        pass
    finally:
        os.close(master)

    p.wait()
    return p.returncode, captured_output.decode("utf-8", errors="replace")


def main(llm, agent_mode: bool):
    print("Welcome to LSH (LLM Shell). Type 'exit' or 'quit' to quit.\n")
    
    while True:
        try:
            cwd = os.getcwd()
            prompt = f"\033[1;32mlsh\033[0m:\033[1;34m{cwd}\033[0m$ "
            user_input = input(prompt).strip()
            
            if not user_input:
                continue
            if user_input in ["exit", "quit"]:
                print("Goodbye!")
                break

            try:
                tokens = shlex.split(user_input)
                if not tokens:
                    continue
                base_cmd = tokens[0]
            except ValueError:
                base_cmd = user_input.split()[0]

            # Built-in: cd
            if base_cmd == "cd":
                target = os.path.expanduser(tokens[1]) if len(tokens) > 1 else os.path.expanduser("~")
                try:
                    os.chdir(target)
                except Exception as e:
                    print(f"cd: {e}")
                continue

            # Interactive tools (no capture, no LLM help)
            if base_cmd in IGNORE_LIST:
                run_interactive(tokens)
                continue

            # Regular command with capture
            exit_code, full_output = run_capturing(user_input)

            if exit_code != 0:
                response = ask_llm_for_fix(llm, user_input, full_output, exit_code)
                fixed_cmd = extract_code_block(response)
                
                print(f"\n\033[1;33mSuggested Fix:\033[0m {fixed_cmd}")
                
                if agent_mode:
                    print("\033[1;35mAgent Mode: executing fix...\033[0m")
                    run_capturing(fixed_cmd)
                else:
                    confirm = input("\nRun this command? [y/N] ").strip().lower()
                    if confirm == 'y':
                        run_capturing(fixed_cmd)

        except KeyboardInterrupt:
            print("^C")
        except EOFError:
            print("\nGoodbye!")
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LSH - LLM-powered shell assistant")
    parser.add_argument("--agent", action="store_true", help="Enable agent mode (auto-run fixes)")
    parser.add_argument("--llm", default="gemma3n:latest", help="Ollama model to use (default: gemma3n:latest)")
    parser.add_argument("--ollama", default="http://localhost:11434", help="Ollama host (default: http://localhost:11434)")

    args = parser.parse_args()

    # Now we initialize the LLM *after* parsing args
    llm = setup_llm(model_name=args.llm, ollama_host=args.ollama)

    # Start the shell
    main(llm=llm, agent_mode=args.agent)
