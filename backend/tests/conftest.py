"""Shared test fixtures."""
import pytest
import sys
from pathlib import Path

# Ensure backend modules are importable
sys.path.insert(0, str(Path(__file__).parent.parent))
