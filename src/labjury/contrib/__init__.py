"""Optional, dependency-carrying reference plugins.

Everything under ``labjury.contrib`` may import third-party packages (behind
the matching ``pip install labjury[...]`` extra). The rule that keeps core
zero-dependency: **core never imports ``labjury.contrib``** — these modules
are imported only by the code that opts into the extra.
"""
