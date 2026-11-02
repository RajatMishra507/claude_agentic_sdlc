from engine import runner, validators

PHASE = {"required_headings": ["Overview"]}
BODY = "## Overview\n" + "Real content describing the feature in enough detail. " * 8


def errors_for(extra):
    return validators.validate_markdown(PHASE, BODY + extra)


def test_proper_noun_todo_is_not_a_placeholder():
    assert errors_for("\nSource: https://x.atlassian.net/wiki/pages/1/Todo+List+User+Story, 'Todo List'") == []


def test_uppercase_markers_and_lorem_ipsum_are_still_placeholders():
    for text in ("TODO: fill in", "TBD", "FIXME later", "Lorem Ipsum dolor"):
        assert any("placeholder" in e for e in errors_for("\n" + text)), text


def test_agent_analytics_output_is_ignored_by_the_workspace_snapshot(bare_project):
    before = runner.snapshot()
    target = bare_project / "docs" / "codemie" / "analytics"
    target.mkdir(parents=True)
    (target / "codemie-analytics-x.json").write_text("{}")
    assert runner.changed_files(before, runner.snapshot()) == []
    (bare_project / "docs" / "other.md").write_text("changed")
    assert runner.changed_files(before, runner.snapshot()) == ["docs/other.md"]
