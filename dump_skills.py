import json
from tubecli.core.skill import skill_manager

skills = [s.to_dict() for s in skill_manager.get_all()]
with open("skills_dump.json", "w", encoding="utf-8") as f:
    json.dump(skills, f, ensure_ascii=False, indent=2)
print("Dumped to skills_dump.json")
