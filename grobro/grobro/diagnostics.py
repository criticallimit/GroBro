"""Optional diagnostics bootstrap for Better GroBro.

Diagnostics are deliberately kept separate from the normal bridge setup. The
individual hooks remain passive and only observe traffic already processed by
GroBro. This module provides one stable entry point so the application startup
does not need to know how each diagnostic observer is implemented.
"""

from grobro.grobro.noah_traffic_hook import install_noah_traffic_debug_hook
from grobro.grobro.register_debug import install_register_debug_hook


def install_optional_diagnostics() -> None:
    """Install all passive diagnostics using their existing feature gates."""
    install_register_debug_hook()
    install_noah_traffic_debug_hook()
