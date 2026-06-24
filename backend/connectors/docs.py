"""Documentation connector - loads existing docs for RAG indexing."""
from pathlib import Path


MOCK_DIR = Path(__file__).parent.parent / "mock_data" / "docs"


class DocsConnector:
    """Loads documentation files from a directory."""

    def __init__(self, docs_dir: Path | None = None):
        self.docs_dir = docs_dir or MOCK_DIR

    def get_all_documents(self) -> list[dict[str, str]]:
        """Return all documents with their path and content."""
        documents = []
        for doc_path in sorted(self.docs_dir.glob("**/*.md")):
            documents.append({
                "path": str(doc_path.relative_to(self.docs_dir)),
                "title": doc_path.stem.replace("-", " ").title(),
                "content": doc_path.read_text(),
            })
        return documents
