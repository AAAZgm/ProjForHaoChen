"""Launch system desktop helpers without the frozen runtime's library paths."""
import os
import subprocess
import sys


def system_environment():
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        for name in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            original = env.pop(name + "_ORIG", None)
            env.pop(name, None)
            if original:
                env[name] = original
    return env


def open_target(target):
    return subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(target)],
                            env=system_environment(), stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
