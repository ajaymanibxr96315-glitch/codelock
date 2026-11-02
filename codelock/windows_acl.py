"""Read-only ACL inspection for the protected hosts-helper installation.

The GUI runs as a standard user. Before it launches an elevated helper it must
know that the installed script, manifest and directory cannot be changed by a
standard user. The DACL is parsed here and any write-capable allow ACE for a
non-administrative trustee is treated as a failure.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path
from typing import Iterable

SE_FILE_OBJECT = 1
OWNER_SECURITY_INFORMATION = 0x00000001
DACL_SECURITY_INFORMATION = 0x00000004
ACL_SIZE_INFORMATION = 2
ACCESS_ALLOWED_ACE_TYPE = 0
ACCESS_ALLOWED_OBJECT_ACE_TYPE = 5
ACE_OBJECT_TYPE_PRESENT = 0x1
ACE_INHERITED_OBJECT_TYPE_PRESENT = 0x2
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400

FILE_WRITE_DATA = 0x00000002
FILE_APPEND_DATA = 0x00000004
FILE_WRITE_EA = 0x00000010
FILE_DELETE_CHILD = 0x00000040
FILE_WRITE_ATTRIBUTES = 0x00000100
DELETE = 0x00010000
WRITE_DAC = 0x00040000
WRITE_OWNER = 0x00080000
GENERIC_ALL = 0x10000000
GENERIC_WRITE = 0x40000000

WRITE_MASK = (
    FILE_WRITE_DATA
    | FILE_APPEND_DATA
    | FILE_WRITE_EA
    | FILE_DELETE_CHILD
    | FILE_WRITE_ATTRIBUTES
    | DELETE
    | WRITE_DAC
    | WRITE_OWNER
    | GENERIC_ALL
    | GENERIC_WRITE
)

SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"
TRUSTED_INSTALLER_SID = (
    "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
)
CREATOR_OWNER_SID = "S-1-3-0"
OWNER_RIGHTS_SID = "S-1-3-4"
SAFE_OWNER_SIDS = {SYSTEM_SID, ADMINISTRATORS_SID, TRUSTED_INSTALLER_SID}

TOKEN_QUERY = 0x0008
TOKEN_USER_INFORMATION = 1


class _ACL_SIZE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("AceCount", wintypes.DWORD),
        ("AclBytesInUse", wintypes.DWORD),
        ("AclBytesFree", wintypes.DWORD),
    ]


class _ACE_HEADER(ctypes.Structure):
    _fields_ = [
        ("AceType", ctypes.c_ubyte),
        ("AceFlags", ctypes.c_ubyte),
        ("AceSize", ctypes.c_ushort),
    ]


def _load_api():
    if os.name != "nt":
        return None, None
    return (
        ctypes.WinDLL("advapi32", use_last_error=True),
        ctypes.WinDLL("kernel32", use_last_error=True),
    )


_ADVAPI32, _KERNEL32 = _load_api()


def _is_admin_process() -> bool:
    if os.name != "nt":
        return False
    try:
        advapi32 = _ADVAPI32
        advapi32.AllocateAndInitializeSid.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ubyte,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi32.AllocateAndInitializeSid.restype = wintypes.BOOL
        advapi32.CheckTokenMembership.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.BOOL),
        ]
        advapi32.CheckTokenMembership.restype = wintypes.BOOL
        advapi32.FreeSid.argtypes = [ctypes.c_void_p]
        identifier_authority = ctypes.c_void_p()
        # SECURITY_NT_AUTHORITY = {0,0,0,0,0,5}
        authority = (ctypes.c_ubyte * 6)(0, 0, 0, 0, 0, 5)
        sid = ctypes.c_void_p()
        if not advapi32.AllocateAndInitializeSid(
            ctypes.byref(authority),
            2,
            32,
            544,
            0,
            0,
            0,
            0,
            0,
            0,
            ctypes.byref(sid),
        ):
            return False
        try:
            member = wintypes.BOOL()
            if not advapi32.CheckTokenMembership(None, sid, ctypes.byref(member)):
                return False
            return bool(member.value)
        finally:
            advapi32.FreeSid(sid)
    except (OSError, AttributeError):
        return False


def _setup_prototypes() -> None:
    if _ADVAPI32 is None:
        return
    advapi32 = _ADVAPI32
    kernel32 = _KERNEL32
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.GetAclInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_int,
    ]
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetFileAttributesW.argtypes = [wintypes.LPWSTR]
    kernel32.GetFileAttributesW.restype = wintypes.DWORD
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p


_setup_prototypes()

_current_sid_cache: str | None = None


def current_user_sid() -> str:
    global _current_sid_cache
    if _current_sid_cache is not None:
        return _current_sid_cache
    if _ADVAPI32 is None:
        return ""
    token = wintypes.HANDLE()
    if not _ADVAPI32.OpenProcessToken(
        _KERNEL32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)
    ):
        return ""
    try:
        size = wintypes.DWORD()
        _ADVAPI32.GetTokenInformation(
            token, TOKEN_USER_INFORMATION, None, 0, ctypes.byref(size)
        )
        buffer = ctypes.create_string_buffer(size.value)
        if not _ADVAPI32.GetTokenInformation(
            token,
            TOKEN_USER_INFORMATION,
            buffer,
            size.value,
            ctypes.byref(size),
        ):
            return ""
        sid_pointer = ctypes.c_void_p.from_buffer(buffer).value
        _current_sid_cache = _sid_to_string(sid_pointer)
        return _current_sid_cache
    finally:
        _KERNEL32.CloseHandle(token)


def _sid_to_string(sid: int | ctypes.c_void_p | None) -> str:
    if _ADVAPI32 is None or not sid:
        return ""
    pointer = wintypes.LPWSTR()
    if not _ADVAPI32.ConvertSidToStringSidW(ctypes.c_void_p(sid), ctypes.byref(pointer)):
        return ""
    try:
        return pointer.value or ""
    finally:
        _KERNEL32.LocalFree(pointer)


def _is_safe_trustee(sid: str, owner_sid: str, elevated: bool) -> bool:
    if not sid:
        return False
    if sid in SAFE_OWNER_SIDS:
        return True
    if sid in (CREATOR_OWNER_SID, OWNER_RIGHTS_SID):
        return owner_sid in SAFE_OWNER_SIDS
    if elevated and sid == current_user_sid():
        return True
    return False


def inspect_path_acl(path: str | Path) -> list[str]:
    """Return a list of reasons a standard user could change this path."""
    if os.name != "nt":
        return ["acl_check_unavailable"]
    if _ADVAPI32 is None:
        return ["acl_check_unavailable"]

    candidate = str(path)
    attributes = _KERNEL32.GetFileAttributesW(candidate)
    if attributes == INVALID_FILE_ATTRIBUTES:
        return ["missing"]
    if attributes & FILE_ATTRIBUTE_REPARSE_POINT:
        return ["reparse_point"]

    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = _ADVAPI32.GetNamedSecurityInfoW(
        candidate,
        SE_FILE_OBJECT,
        OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result != 0:
        return [f"acl_error:{result}"]

    try:
        owner_sid = _sid_to_string(owner.value)
        elevated = _is_admin_process()
        safe_owner = owner_sid in SAFE_OWNER_SIDS or (
            elevated and owner_sid == current_user_sid()
        )
        problems: list[str] = []
        if not safe_owner:
            problems.append(f"owner_not_protected:{owner_sid or 'unknown'}")
        if not dacl.value:
            problems.append("null_dacl")
            return problems

        info = _ACL_SIZE_INFORMATION()
        if not _ADVAPI32.GetAclInformation(
            dacl, ctypes.byref(info), ctypes.sizeof(info), ACL_SIZE_INFORMATION
        ):
            return problems + ["acl_unreadable"]

        seen: set[str] = set()
        for index in range(info.AceCount):
            ace = ctypes.c_void_p()
            if not _ADVAPI32.GetAce(dacl, index, ctypes.byref(ace)):
                problems.append("ace_unreadable")
                break
            header = ctypes.cast(ace, ctypes.POINTER(_ACE_HEADER)).contents
            if header.AceType not in (
                ACCESS_ALLOWED_ACE_TYPE,
                ACCESS_ALLOWED_OBJECT_ACE_TYPE,
            ):
                continue
            mask = ctypes.c_uint32.from_address(ace.value + 4).value
            if not (mask & WRITE_MASK):
                continue
            if header.AceType == ACCESS_ALLOWED_ACE_TYPE:
                sid_offset = 8
            else:
                flags = ctypes.c_uint32.from_address(ace.value + 8).value
                sid_offset = 12
                if flags & ACE_OBJECT_TYPE_PRESENT:
                    sid_offset += 16
                if flags & ACE_INHERITED_OBJECT_TYPE_PRESENT:
                    sid_offset += 16
            trustee = _sid_to_string(ace.value + sid_offset)
            if _is_safe_trustee(trustee, owner_sid, elevated):
                continue
            label = trustee or "unknown"
            if label not in seen:
                seen.add(label)
                problems.append(f"writable_by:{label}")
        return problems
    finally:
        if descriptor.value:
            _KERNEL32.LocalFree(descriptor)


def inspect_installation_acl(
    install_dir: str | Path, files: Iterable[str | Path]
) -> list[str]:
    """ACL problems for the installation directory and its protected files."""
    problems = [f"dir:{item}" for item in inspect_path_acl(install_dir)]
    for item in files:
        path = Path(item)
        problems.extend(
            f"{path.name}:{problem}" for problem in inspect_path_acl(path)
        )
    return problems
