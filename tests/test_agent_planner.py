from dataclasses import dataclass

from scripts import agent_loop


@dataclass
class _Block:
    type: str
    text: str = ""
    name: str = ""
    id: str = ""
    input: dict | None = None


class _Response:
    def __init__(self, blocks):
        self.content = blocks


def test_plan_next_action_extracts_tool_and_text():
    response = _Response(
        [
            _Block(type="text", text="Thinking..."),
            _Block(
                type="tool_use",
                name="scroll",
                id="tool-1",
                input={"direction": "down", "reasoning": "Need more content"},
            ),
        ]
    )

    action, text_parts = agent_loop._plan_next_action(response)

    assert action is not None
    assert action.name == "scroll"
    assert action.tool_use_id == "tool-1"
    assert action.params["direction"] == "down"
    assert action.reasoning == "Need more content"
    assert text_parts == ["Thinking..."]


def test_plan_next_action_returns_none_without_tool():
    response = _Response([_Block(type="text", text="No tool this turn")])
    action, text_parts = agent_loop._plan_next_action(response)

    assert action is None
    assert text_parts == ["No tool this turn"]
