"""Documentation connector - loads existing docs for RAG indexing.

Supports:
- Markdown files from a directory
- Recursive discovery
- Graceful handling of encoding issues
"""
import logging
from pathlib import Path

logger = logging.getLogger("release_agent")
MOCK_DIR = Path(__file__).parent.parent / "mock_data" / "docs"


class DocsConnector:
    """Loads documentation files from a directory."""

    def __init__(self, docs_dir: Path | None = None):
        self.docs_dir = docs_dir or MOCK_DIR

    def get_all_documents(self) -> list[dict[str, str]]:
        """Return all documents with their path, title, and content.
        
        Handles:
        - Non-existent directories (returns empty)
        - Encoding errors (skips file with warning)
        - Empty files (skipped)
        """
        if not self.docs_dir.exists():
            logger.warning(f"Docs directory not found: {self.docs_dir}")
            return []

        documents = []
        for doc_path in sorted(self.docs_dir.glob("**/*.md")):
            try:
                content = doc_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, IOError) as e:
                logger.warning(f"Skipping {doc_path}: {e}")
                continue

            if not content.strip():
                continue

            documents.append({
                "path": str(doc_path.relative_to(self.docs_dir)),
                "title": doc_path.stem.replace("-", " ").title(),
                "content": content,
            })

        return documents
