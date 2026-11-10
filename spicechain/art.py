"""Banner for the interactive CLI."""

TITLE = r"""
 ____        _           ____ _           _
/ ___| _ __ (_) ___ ___ / ___| |__   __ _(_)_ __
\___ \| '_ \| |/ __/ _ \ |   | '_ \ / _` | | '_ \
 ___) | |_) | | (_|  __/ |___| | | | (_| | | | | |
|____/| .__/|_|\___\___|\____|_| |_|\__,_|_|_| |_|
      |_|
"""

TAGLINE = "for Boiler Guitar Shop"


def banner() -> str:
    """The SpiceChain title with the tagline under it."""
    return TITLE.strip("\n")
