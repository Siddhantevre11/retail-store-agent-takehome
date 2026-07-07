from tests.smoke import format_transcript, parse_prompt_file


def test_format_transcript_renders_a_turn_with_no_tool_calls():
    transcript = format_transcript(
        turns=[
            (
                "Return a hoodie from order O-1012.",
                [],
                "Which hoodie do you mean — order O-1012 has three.",
            )
        ]
    )

    assert transcript == (
        "> Return a hoodie from order O-1012.\n"
        "< Which hoodie do you mean — order O-1012 has three."
    )


def test_parse_prompt_file_single_line_is_one_conversation_with_one_turn():
    conversations = parse_prompt_file("Ring up one Canvas Tote for a walk-in, cash, dated today.")

    assert conversations == [
        ["Ring up one Canvas Tote for a walk-in, cash, dated today."]
    ]


def test_parse_prompt_file_consecutive_lines_are_turns_in_one_conversation():
    conversations = parse_prompt_file(
        "Ring up one Canvas Tote for Sarah Chen, cash, dated today.\n"
        "Now sell her a Ceramic Mug too, same terms."
    )

    assert conversations == [
        [
            "Ring up one Canvas Tote for Sarah Chen, cash, dated today.",
            "Now sell her a Ceramic Mug too, same terms.",
        ]
    ]


def test_format_transcript_renders_one_turn_with_one_tool_call():
    transcript = format_transcript(
        turns=[
            (
                "Ring up one Canvas Tote for a walk-in, cash, dated today.",
                [("create_sale", {"lines": []}, {"order_id": "O-1015"})],
                "Rung up order O-1015.",
            )
        ]
    )

    assert transcript == (
        "> Ring up one Canvas Tote for a walk-in, cash, dated today.\n"
        "  [tool] create_sale({'lines': []}) -> {'order_id': 'O-1015'}\n"
        "< Rung up order O-1015."
    )


def test_format_transcript_renders_two_turns_with_own_tool_calls():
    transcript = format_transcript(
        turns=[
            (
                "Ring up one Canvas Tote for Sarah Chen, cash, dated today.",
                [("create_sale", {"lines": []}, {"order_id": "O-1015"})],
                "Rung up order O-1015.",
            ),
            (
                "Now sell her a Ceramic Mug too, same terms.",
                [("create_sale", {"lines": []}, {"order_id": "O-1016"})],
                "Rung up order O-1016.",
            ),
        ]
    )

    assert transcript == (
        "> Ring up one Canvas Tote for Sarah Chen, cash, dated today.\n"
        "  [tool] create_sale({'lines': []}) -> {'order_id': 'O-1015'}\n"
        "< Rung up order O-1015.\n"
        "\n"
        "> Now sell her a Ceramic Mug too, same terms.\n"
        "  [tool] create_sale({'lines': []}) -> {'order_id': 'O-1016'}\n"
        "< Rung up order O-1016."
    )


def test_parse_prompt_file_blank_line_separates_conversations():
    conversations = parse_prompt_file(
        "Ring up one Canvas Tote for a walk-in, cash, dated today.\n"
        "\n"
        "What are my top 5 products by profit margin last month?"
    )

    assert conversations == [
        ["Ring up one Canvas Tote for a walk-in, cash, dated today."],
        ["What are my top 5 products by profit margin last month?"],
    ]
