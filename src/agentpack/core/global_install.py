"""Backward-compat shim — moved to agentpack.integrations.global_install."""
from agentpack.integrations.global_install import (  # noqa: F401
    install_git_template_hooks,
    configure_git_template_dir,
    remove_git_template_hooks,
    install_shell_hook,
    remove_shell_hook,
    _GIT_TEMPLATE_DIR,
    _AGENTPACK_MARKER,
    _SHELL_MARKER_START,
    _SHELL_MARKER_END,
    _HOOK_SCRIPTS,
    _detect_rc_file,
)
