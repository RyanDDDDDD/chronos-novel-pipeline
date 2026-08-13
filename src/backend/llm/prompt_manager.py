import os
import re
import sys

from utils.paths import SKILLS_DIR


class PromptManager:
    """Context assembler: Agent Prompt loading, input file reading, text cleaning, output file writing.

    All methods are static methods, and the directory path is passed in as an explicit parameter to facilitate test injection and mocking."""


    @staticmethod
    def load_global_base(skills_dir: str = SKILLS_DIR) -> str:
        """
Universal base: injected to all agents. Architectural components, placed in skills/."""
        path = os.path.join(skills_dir, "global_base.md")
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            return f"<Global_Base>\n{f.read()}\n</Global_Base>"

    @staticmethod
    def load_agent_prompt(
        agent_name: str,
        role: str | None,
        agents_dir: str,
    ) -> str:
        agent_dir = os.path.join(agents_dir, agent_name)
        if not os.path.isdir(agent_dir):
            print(f"[WARN] agent directory not found: {agent_dir}", file=sys.stderr)
            return ""
        parts = []
        global_base = PromptManager.load_global_base()
        if global_base:
            parts.append(global_base)
        prompt_name = role if role else agent_name
        agent_md = os.path.join(agent_dir, f"{prompt_name}.md")
        if os.path.exists(agent_md):
            with open(agent_md, "r", encoding="utf-8") as f:
                parts.append(f"<System_Instructions>\n{f.read()}\n</System_Instructions>")
        example_names = [f"{role}_EXAMPLE.md"] if role else []
        for example_name in example_names:
            example_md = os.path.join(agent_dir, example_name)
            if os.path.exists(example_md):
                with open(example_md, "r", encoding="utf-8") as f:
                    parts.append(f"<Few_Shot_Examples>\n{f.read()}\n</Few_Shot_Examples>")
                break
        return "\n\n".join(parts)

    @staticmethod
    def load_agent_refine_analysis(agent_name: str, role: str | None, agents_dir: str) -> str:
        names = ([f"{role}_refine_analysis.md", "refine_analysis.md"] if role else ["refine_analysis.md"])
        for name in names:
            path = os.path.join(agents_dir, agent_name, name)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
        return ""

    @staticmethod
    def has_refine_analysis(agent_name: str, role: str | None, agents_dir: str) -> bool:
        names = (
            [f"{role}_refine_analysis.md", "refine_analysis.md"]
            if role
            else ["refine_analysis.md"]
        )
        agent_dir = os.path.join(agents_dir, agent_name)
        return any(os.path.exists(os.path.join(agent_dir, n)) for n in names)

    @staticmethod
    def strip_preamble(text: str) -> str:
        m = re.search(r"\*\*【", text)
        return text[m.start():] if m else text

    @staticmethod
    def strip_status_header(text: str) -> str:
        """Cut off the status header line (**[...]**) at the top of the file, and only keep the main content and pass it to the downstream."""
        return re.sub(r"^\*\*【[^】]+】[^\n]*\*\*\s*\n+", "", text)

    @staticmethod
    def save_output(output_filename: str, content: str, chapter: int, chapters_dir: str) -> str:
        output_filename = os.path.basename(output_filename)
        target_dir = os.path.join(chapters_dir, f"第{chapter}章")
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, output_filename)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(PromptManager.strip_preamble(content))
        return target_path

    @staticmethod
    def save_assembled(output_filename: str, content: str, chapter: int, chapters_dir: str) -> str:
        """
Save multi-segment assembly results - each segment has been per-segment strip_preamble, and the whole is no longer cut."""
        output_filename = os.path.basename(output_filename)
        target_dir = os.path.join(chapters_dir, f"第{chapter}章")
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, output_filename)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        return target_path
