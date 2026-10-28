"""Best-effort Windows QoS for our own media-processing children."""

import ctypes
from ctypes import wintypes
import logging
import os

LOG = logging.getLogger("bili_video_tool")
_PROCESS_SET_INFORMATION = 0x0200
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_POWER_THROTTLING = 4
_EXECUTION_SPEED = 0x1


class _PowerThrottlingState(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_uint32),
                ("ControlMask", ctypes.c_uint32),
                ("StateMask", ctypes.c_uint32)]


def _windows_api():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    for name in ("GetProcessInformation", "SetProcessInformation"):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        function.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def request_high_qos(pid: int) -> bool:
    """Opt this child out of automatic execution-speed throttling, if supported.

    Zero masks leave QoS to Windows. Controlling EXECUTION_SPEED explicitly
    with its state bit cleared requests HighQoS. Preserve all other policy bits;
    do not change priority, affinity, timer policy or the system power plan.
    Failure is diagnostic only: older Windows and restricted accounts can still
    export using their existing scheduling policy.
    """
    if os.name != "nt":
        return False
    try:
        kernel = _windows_api()
        handle = kernel.OpenProcess(
            _PROCESS_SET_INFORMATION | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            state = _PowerThrottlingState(1, 0, 0)
            if not kernel.GetProcessInformation(
                handle, _PROCESS_POWER_THROTTLING, ctypes.byref(state), ctypes.sizeof(state)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            state.ControlMask |= _EXECUTION_SPEED
            state.StateMask &= ~_EXECUTION_SPEED
            if not kernel.SetProcessInformation(
                handle, _PROCESS_POWER_THROTTLING, ctypes.byref(state), ctypes.sizeof(state)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel.CloseHandle(handle)
    except Exception as exc:
        # This optional optimization must never prevent processing or cleanup.
        LOG.info("FFmpeg HighQoS unavailable (pid=%s): %s; keeping existing scheduling", pid, exc)
        return False
    LOG.info("FFmpeg HighQoS applied (pid=%s, control=%s, state=%s)",
             pid, state.ControlMask, state.StateMask)
    return True
