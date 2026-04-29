"""Backward-compat shim — moved to agentpack.integrations.git_hooks."""
from agentpack.integrations.git_hooks import (  # noqa: F401
    install_git_hooks,
    remove_git_hooks,
    _HOOK_EVENTS,
    _AGENTPACK_MARKER,
    _hook_script,
)
