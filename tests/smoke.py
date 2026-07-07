import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from agent.loop import run_agent_turn
from agent.runner import DATA_DIR, MODEL, build_tool_registry
from agent.schemas import SYSTEM_PROMPT, TOOL_SCHEMAS
from agent.session import SessionState
from db.loader import bootstrap_db


def format_transcript(turns):
    blocks = []
    for prompt, tool_calls, reply in turns:
        lines = [f"> {prompt}"]
        for name, args, result in tool_calls:
            lines.append(f"  [tool] {name}({args!r}) -> {result!r}")
        lines.append(f"< {reply}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def parse_prompt_file(text):
    conversations = []
    current = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                conversations.append(current)
                current = []
        else:
            current.append(line)
    if current:
        conversations.append(current)
    return conversations


def run_conversation_per_turn(client, prompts, data_dir=DATA_DIR):
    """Like agent.runner.run_conversation, but keeps each turn's tool calls
    segmented instead of flattened, so the transcript can show which tool
    calls belong to which prompt. Not asserted against — this is a human
    review tool, not the harness.
    """
    conn = bootstrap_db(data_dir)
    session = SessionState()
    tool_registry = build_tool_registry(conn, session)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    turns = []
    for prompt in prompts:
        messages.append({"role": "user", "content": prompt})
        this_turn_log = []
        messages, reply = run_agent_turn(
            client,
            MODEL,
            messages,
            tool_registry,
            TOOL_SCHEMAS,
            log_fn=lambda name, args, result: this_turn_log.append((name, args, result)),
        )
        turns.append((prompt, this_turn_log, reply))
    return turns


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    prompt_file = sys.argv[1] if len(sys.argv) > 1 else "tests/smoke_prompts.txt"
    conversations = parse_prompt_file(Path(prompt_file).read_text(encoding="utf-8"))

    for i, prompts in enumerate(conversations, start=1):
        turns = run_conversation_per_turn(client, prompts)
        print(f"===== conversation {i}/{len(conversations)} =====")
        print(format_transcript(turns))
        print()


if __name__ == "__main__":
    main()
