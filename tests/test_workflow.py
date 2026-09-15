from pathlib import Path

import yaml


def test_github_workflow_has_schedule_manual_run_validation_and_pages() -> None:
    path = Path(__file__).parents[1] / ".github" / "workflows" / "update-calendar.yml"
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    triggers = workflow["on"]
    assert {item["cron"] for item in triggers["schedule"]} == {
        "0 0 * * *",
        "0 12 * * *",
    }
    assert "workflow_dispatch" in triggers
    assert workflow["permissions"] == {
        "contents": "write",
        "pages": "write",
        "id-token": "write",
    }

    steps = workflow["jobs"]["update"]["steps"]
    rendered = "\n".join(str(step) for step in steps)
    assert "python -m src.main" in rendered
    assert "timeout 180s" in rendered
    assert "python -m src.main --offline" in rendered
    assert "python -m src.validate dist" in rendered
    assert "chore: update finance calendar" in rendered
    assert "actions/upload-pages-artifact@v3" in rendered
    assert workflow["jobs"]["deploy"]["needs"] == "update"
