import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

from agent.loop import run_agent_turn
from agent.runner import DATA_DIR, MODEL, SYSTEM_PROMPT, TOOL_SCHEMAS, build_tool_registry
from agent.session import SessionState
from db.loader import bootstrap_db


def _log_tool_call(name, args, result):
    print(f"  [tool] {name}({args}) -> {result}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    conn = bootstrap_db(DATA_DIR)
    session = SessionState()
    tool_registry = build_tool_registry(conn, session)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("Retail Store Agent. Type an instruction, or 'exit' to quit.")
    while True:
        user_input = input("> ").strip()
        if user_input.lower() in {"exit", "quit"}:
            break

        messages.append({"role": "user", "content": user_input})
        messages, reply = run_agent_turn(
            client, MODEL, messages, tool_registry, TOOL_SCHEMAS, log_fn=_log_tool_call
        )
        print(reply)


if __name__ == "__main__":
    main()
