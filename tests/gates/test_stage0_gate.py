from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_stage0_reference_documents_exist():
    assert (ROOT / "docs" / "reference-analysis.md").is_file()
    assert (ROOT / "docs" / "architecture-decisions.md").is_file()
    assert (ROOT / "docs" / "stage-gates.md").is_file()


def test_platform_has_no_reference_or_rag_path_dependency():
    source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "agent_platform").rglob("*.py"))
    forbidden = (
        "zhongwen-shortdrama", "agent1", "D:\\AI\\Chinese", "faiss", "chromadb",
        "milvus", "embedding", "graphrag", "tavily", "mcp",
    )
    lowered = source.lower()
    assert not [token for token in forbidden if token.lower() in lowered]


def test_stage0_documents_state_the_required_boundaries():
    analysis = (ROOT / "docs" / "reference-analysis.md").read_text(encoding="utf-8").lower()
    decisions = (ROOT / "docs" / "architecture-decisions.md").read_text(encoding="utf-8").lower()
    for token in ("reviewgate", "stable", "evidence", "tool bridge"):
        assert token in analysis
    for token in ("workflow", "持久化", "rag", "模块化单体"):
        assert token in decisions
