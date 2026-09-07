"""Primes a valid pinned-provider config before any test module imports
src.agent_config / src.server - both resolve PROVIDER_ID/MODEL once at
import time (see agent_config.py's module docstring) and raise
AgentConfigError immediately if AI_AGENT_PROVIDER or its API key isn't
set, which would otherwise break collection of test_server.py.

Set directly on os.environ (not via a monkeypatch fixture, which only
applies inside a running test) since this must be in place before pytest
even imports the test modules. test_agent_config.py's own tests still
freely override/clear these per test via monkeypatch - that only affects
the duration of each test, never this module-level default.
"""

import os

os.environ.setdefault("AI_AGENT_PROVIDER", "claude")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
