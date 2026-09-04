import subprocess
from pathlib import Path

import pytest

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
    assert "real-database-password" not in readme
    assert "DEEPSEEK_API_KEY=token" not in readme


def test_contributor_guide_exists_with_required_safety_rule() -> None:
    guide = ROOT.joinpath("AGENTS.md").read_text(encoding="utf-8")

    assert guide.startswith("# Repository Guidelines")
    assert 200 <= len(guide.split()) <= 400
    assert "INSERT" in guide
    assert "strictly read-only" in guide


@pytest.mark.parametrize(
    ("target", "variables", "expected"),
    [
        ("docker-build", (), ("docker build", "profitlens:local")),
        ("docker-chat", (), ("docker run", "--env-file .env", "chat")),
        (
            "docker-ask",
            ("QUESTION=分析昨天利润下降原因",),
            ("docker run", '"profitlens:local" ask', "分析昨天利润下降原因"),
        ),
        ("docker-db-check", (), ("docker run", "db-check")),
    ],
)
def test_docker_make_targets_render_runnable_commands(
    target: str,
    variables: tuple[str, ...],
    expected: tuple[str, ...],
) -> None:
    result = subprocess.run(
        ("make", "--dry-run", target, *variables),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert all(fragment in result.stdout for fragment in expected)
