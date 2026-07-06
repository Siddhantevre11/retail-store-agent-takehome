import json
from types import SimpleNamespace

from agent.loop import run_agent_turn


class FakeToolCall:
    def __init__(self, call_id, name, arguments):
        self.id = call_id
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments))


class FakeResponse:
    def __init__(self, content=None, tool_calls=None):
        message = SimpleNamespace(content=content, tool_calls=tool_calls)
        self.choices = [SimpleNamespace(message=message)]


class FakeClient:
    """Stands in for the OpenAI client — the one real external boundary here."""

    def __init__(self, responses):
        self._responses = iter(responses)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        return next(self._responses)


def test_run_agent_turn_executes_tool_call_and_logs_it():
    tool_call = FakeToolCall("call_1", "find_sku", {"product_name": "Canvas Tote"})
    client = FakeClient(
        [
            FakeResponse(tool_calls=[tool_call]),
            FakeResponse(content="Here's the receipt."),
        ]
    )

    logged = []
    messages = [{"role": "user", "content": "ring up a tote"}]
    tool_registry = {"find_sku": lambda product_name: {"sku": "TOTE"}}

    _, final_reply = run_agent_turn(
        client,
        "gpt-5.4-mini",
        messages,
        tool_registry,
        tool_schemas=[],
        log_fn=lambda *a: logged.append(a),
    )

    assert final_reply == "Here's the receipt."
    assert logged == [("find_sku", {"product_name": "Canvas Tote"}, {"sku": "TOTE"})]
