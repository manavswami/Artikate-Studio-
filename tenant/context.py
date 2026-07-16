"""
Stores the current tenant for the lifetime of a request.

Initially this implementation uses thread-local storage because
the assignment explicitly asks for it.

In ANSWERS.md we will explain why thread-local storage is unsafe
for async Django views and why contextvars should be used instead.
"""

import threading


# One storage object per thread.
_thread_local = threading.local()


def set_current_tenant(tenant):
    """
    Store the current tenant.

    Called by middleware before the request reaches the view.
    """
    _thread_local.tenant = tenant


def get_current_tenant():
    """
    Return the tenant associated with the current request.

    Returns:
        Tenant instance or None.
    """
    return getattr(
        _thread_local,
        "tenant",
        None,
    )


def clear_current_tenant():
    """
    Remove the tenant after the request finishes.

    This prevents tenant leakage between requests handled by the
    same worker thread.
    """
    if hasattr(
        _thread_local,
        "tenant",
    ):
        del _thread_local.tenant