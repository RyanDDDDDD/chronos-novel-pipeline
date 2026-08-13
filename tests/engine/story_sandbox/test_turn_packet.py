from engine.story_sandbox.turn_packet import (
    COMPOUND_INSTRUCTION_REMINDER,
    render_turn_packet,
)


def test_render_turn_packet_contains_only_instruction_by_default():
    packet = render_turn_packet(instruction="继续")
    assert packet == f"## 导演本轮指令\n继续\n\n{COMPOUND_INSTRUCTION_REMINDER}"


def test_render_turn_packet_omits_rewrite_section_by_default():
    packet = render_turn_packet(instruction="继续")
    assert "这是一次重写" not in packet


def test_render_turn_packet_appends_rewrite_note_with_previous_prose_and_feedback():
    packet = render_turn_packet(
        instruction="甲乙对峙",
        rewrite_note={"previous_prose": "甲冷冷地看着乙。", "feedback": "语气再冷淡一点"},
    )
    assert "这是一次重写" in packet
    assert "甲乙对峙" in packet  # instruction section untouched, still present
    assert "甲冷冷地看着乙。" in packet
    assert "语气再冷淡一点" in packet


def test_render_turn_packet_rewrite_note_with_empty_feedback_shows_placeholder():
    packet = render_turn_packet(
        instruction="继续", rewrite_note={"previous_prose": "旧正文", "feedback": ""},
    )
    assert "旧正文" in packet
    assert "未填写，按你的判断改一版" in packet


def test_render_turn_packet_prepends_cast_block_before_instruction():
    packet = render_turn_packet(
        instruction="继续", cast_block="## 在场角色档案\n角色：甲（主角）",
    )
    assert packet == (
        f"## 在场角色档案\n角色：甲（主角）\n\n## 导演本轮指令\n继续\n\n{COMPOUND_INSTRUCTION_REMINDER}"
    )


def test_render_turn_packet_prepends_recall_block_before_instruction():
    packet = render_turn_packet(
        instruction="继续", recall_block="## 相关历史/设定回收\n- 【蛊虫】寄生方式驱动力量",
    )
    assert packet == (
        "## 相关历史/设定回收\n- 【蛊虫】寄生方式驱动力量\n\n## 导演本轮指令\n继续\n\n"
        f"{COMPOUND_INSTRUCTION_REMINDER}"
    )


def test_render_turn_packet_orders_cast_block_before_recall_block_before_instruction():
    packet = render_turn_packet(
        instruction="继续",
        cast_block="## 在场角色档案\n角色：甲",
        recall_block="## 相关历史/设定回收\n- 召回内容",
    )
    cast_pos = packet.index("在场角色档案")
    recall_pos = packet.index("相关历史/设定回收")
    instruction_pos = packet.index("导演本轮指令")
    assert cast_pos < recall_pos < instruction_pos


def test_render_turn_packet_prepends_related_cast_block_before_instruction():
    packet = render_turn_packet(
        instruction="继续", related_cast_block="## 相关角色档案\n角色：角色甲",
    )
    assert packet == (
        f"## 相关角色档案\n角色：角色甲\n\n## 导演本轮指令\n继续\n\n{COMPOUND_INSTRUCTION_REMINDER}"
    )


def test_render_turn_packet_orders_cast_before_related_cast_before_recall_before_instruction():
    packet = render_turn_packet(
        instruction="继续",
        cast_block="## 在场角色档案\n角色：甲",
        related_cast_block="## 相关角色档案\n角色：乙",
        recall_block="## 相关历史/设定回收\n- 召回内容",
    )
    cast_pos = packet.index("在场角色档案")
    related_pos = packet.index("相关角色档案")
    recall_pos = packet.index("相关历史/设定回收")
    instruction_pos = packet.index("导演本轮指令")
    assert cast_pos < related_pos < recall_pos < instruction_pos


def test_render_turn_packet_strips_whitespace_only_blocks():
    packet = render_turn_packet(
        instruction="继续", cast_block="   ", related_cast_block="\n\n", recall_block="\n\n",
    )
    assert packet == f"## 导演本轮指令\n继续\n\n{COMPOUND_INSTRUCTION_REMINDER}"


def test_render_turn_packet_cast_and_recall_come_before_rewrite_note():
    packet = render_turn_packet(
        instruction="甲乙对峙",
        cast_block="## 在场角色档案\n角色：甲",
        recall_block="## 相关历史/设定回收\n- 召回内容",
        rewrite_note={"previous_prose": "旧正文", "feedback": "语气再冷淡一点"},
    )
    cast_pos = packet.index("在场角色档案")
    instruction_pos = packet.index("导演本轮指令")
    rewrite_pos = packet.index("这是一次重写")
    assert cast_pos < instruction_pos < rewrite_pos
