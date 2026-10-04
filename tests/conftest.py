"""Test setup: mock mode, fast mock steps, and a throwaway data dir.

These env vars must be set before backend.config is imported.
"""
import os
import tempfile

os.environ["REVIVE_MOCK"] = "1"
os.environ["REVIVE_MOCK_DELAY"] = "0.01"
os.environ["REVIVE_DATA_DIR"] = tempfile.mkdtemp(prefix="revive-test-")
