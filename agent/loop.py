import json


def run_agent_turn(client, model, messages, tool_registry, tool_schemas, log_fn=print):
    """Drive one user turn to completion: call the model, execute any tool
    calls it proposes, feed results back, and repeat until it replies with
    plain text. Returns (updated_messages, final_reply_text).

    The agent only ever proposes tool calls here — it never computes a
    result itself; tool_registry[name](...) is the only thing that runs.
    """
    while True:
        response = client.chat.completions.create(
            model=model, messages=messages, tools=tool_schemas
        )
        message = response.choices[0].message
        messages.append({"role": "assistant", "content": message.content, "tool_calls": message.tool_calls})

        if not message.tool_calls:
            return messages, message.content

        for tool_call in message.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            result = tool_registry[name](**args)
            log_fn(name, args, result)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, default=str),
                }
            )
