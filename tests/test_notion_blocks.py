from scripts.integrations.notion_api import blocks_from_markdown


def test_blocks_from_markdown_basic_types():
    md = "\n".join(
        [
            "# Title",
            "## Section",
            "- bullet",
            "1. numbered",
            "> quote",
            "---",
        ]
    )
    blocks = blocks_from_markdown(md)
    types = [b.get("type") for b in blocks]
    assert types == [
        "heading_1",
        "heading_2",
        "bulleted_list_item",
        "numbered_list_item",
        "quote",
        "divider",
    ]


def test_blocks_from_markdown_code_chunks_rich_text():
    payload = "x" * 4000
    md = "\n".join(
        [
            "```python",
            payload,
            "```",
        ]
    )
    blocks = blocks_from_markdown(md)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "code"
    rich = blocks[0]["code"]["rich_text"]
    assert len(rich) >= 2
    joined = "".join([t["text"]["content"] for t in rich])
    assert joined.startswith("x" * 100)
    assert len(joined) == 4000

