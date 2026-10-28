"""Keep every test away from the real user data.

Modules in engineer/ fix their storage paths (%LOCALAPPDATA%\\RaceEngineer\\...) when first imported. Without this,
whichever test module imports them first decides, and in a full run that was the real profile folder - so
test_memory's reset_store() deleted the user's real strategy.db. Point LOCALAPPDATA at a scratch folder before any
test module is imported.
"""
import os
import tempfile

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="ic_tests_")
