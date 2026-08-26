from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills" / "knowledge"


class KnowledgeSkillService:
    """Load persistent LLM rules without owning deterministic workflow logic."""

    def load(self, name: str) -> str:
        if name == "knowledge":
            path = SKILL_ROOT / "SKILL.md"
        else:
            path = SKILL_ROOT / name / "SKILL.md"
        resolved = path.resolve()
        if not resolved.is_file() or SKILL_ROOT not in resolved.parents:
            raise ValueError(f"Unknown knowledge Skill: {name}")
        return resolved.read_text(encoding="utf-8").strip()

    def combine(self, *names: str) -> str:
        sections = [self.load("knowledge")]
        sections.extend(self.load(name) for name in names)
        return "\n\n---\n\n".join(sections)


knowledge_skill_service = KnowledgeSkillService()
