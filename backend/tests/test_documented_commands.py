from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_makefile_documents_every_public_target() -> None:
    makefile = ROOT.joinpath("Makefile").read_text(encoding="utf-8")
    targets = (
        "install",
        "test",
        "check",
        "demo",
        "agent-demo",
        "model-check",
        "dev",
        "ask",
        "chat",
        "db-check",
    )
    for target in targets:
        assert f"# {target}:" in makefile
        assert f"{target}:" in makefile


def test_readme_documents_real_natural_language_commands_without_secrets() -> None:
    readme = ROOT.joinpath("README.md").read_text(encoding="utf-8")

    for command in ("profitlens ask", "profitlens chat", "profitlens db-check"):
        assert command in readme
    assert "cov_aff" in readme
    assert "mysql+asyncmy://readonly:your-password@" not in readme
    assert "DEEPSEEK_API_KEY=token" not in readme


def test_contributor_guide_exists_with_required_safety_rule() -> None:
    guide = ROOT.joinpath("AGENTS.md").read_text(encoding="utf-8")

    assert guide.startswith("# Repository Guidelines")
    assert 200 <= len(guide.split()) <= 400
    assert "INSERT" in guide
    assert "strictly read-only" in guide
