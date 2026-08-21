"""Explicit sandbox failures safe for the control plane to classify."""


class SandboxError(RuntimeError):
    """Base class for sandbox lifecycle and execution errors."""


class SandboxPolicyError(SandboxError):
    """The requested operation violates a configured policy."""


class SandboxPathError(SandboxPolicyError):
    """A path is outside the workspace or crosses a symbolic link."""


class SandboxClosedError(SandboxError):
    """The session has already been cancelled or closed."""


class SandboxLaunchError(SandboxError):
    """The concrete sandbox runtime could not be started."""
