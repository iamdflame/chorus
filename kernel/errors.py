"""Typed failures at the kernel's invariant boundaries.

The kernel makes a small number of guarantees — an address identifies a request at a causal
position, a replay reproduces a recorded run exactly, a branch inherits its parent's past
and not its future — and every one of them is enforced somewhere by a check. Until now
those checks raised `ValueError` and `RuntimeError`, which has two costs.

**A caller cannot distinguish them.** `except ValueError` around a snapshot load catches a
corrupt file, an unknown parent branch and a malformed effect identically, so the only
recovery available is to give up. With typed errors a caller can rebuild a snapshot, refuse
a fork, or fail the run, which are three different responses to three different problems.

**They read as bugs rather than as invariants.** `ValueError("branch already exists")` looks
like a validation slip. `BranchExists` names a rule the system is enforcing, and the
difference matters when someone is deciding whether to catch it.

Everything here fails closed. There is no error in this module whose recommended handling
is to continue with a default, because every one of them means a guarantee the rest of the
system is built on has stopped holding.
"""

from __future__ import annotations

from typing import Any


class KernelError(Exception):
    """Base for every violated kernel invariant.

    Catching this is catching "the substrate stopped being trustworthy", which is almost
    always the wrong granularity — but it is the right thing for a top-level handler that
    has to decide between failing a request and failing a process.
    """

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.context = context

    def to_dict(self) -> dict[str, Any]:
        return {"error": type(self).__name__, "message": str(self), **self.context}


# -- addressing ---------------------------------------------------------------

class AddressError(KernelError):
    """Something is wrong with how an effect is identified."""


class AddressCollision(AddressError):
    """Two different requests derived the same address.

    This should be impossible — the address is a 128-bit digest over a length-prefixed
    canonical encoding — and if it ever fires it means the encoding stopped being
    canonical, not that a hash collided. Almost certainly a request field that serialises
    differently between runs.
    """


class EffectOutOfOrder(AddressError):
    """An effect was recorded at a sequence position before its own causal parent.

    Ordering is presentation and causality is the DAG, so this is not fatal to a replay —
    but it means the timeline a human reads and the graph the kernel resolves have
    diverged, and one of them is lying.
    """


# -- replay -------------------------------------------------------------------

class ReplayError(KernelError):
    """A replay did not reproduce what was recorded."""


class ReplayDiverged(ReplayError):
    """A replayed run reached a different causal root hash than the recording.

    The single most serious error in this module. It means either the interposition is not
    total — something reached the world without passing the plugin — or a recorded
    response was mutated after the fact.
    """


# -- branches -----------------------------------------------------------------

class BranchError(KernelError):
    """Something is wrong with a timeline."""


class BranchExists(BranchError):
    """A branch id was claimed twice. Silently reusing it would merge two timelines."""


class UnknownBranch(BranchError):
    """A branch was referenced that no store has heard of."""


class ForkPointInvalid(BranchError):
    """A fork was requested at a sequence position the parent never reached."""


# -- persistence --------------------------------------------------------------

class SnapshotError(KernelError):
    """A snapshot could not be trusted."""


class SnapshotCorrupt(SnapshotError):
    """A snapshot is unreadable or internally inconsistent.

    Fails closed rather than loading what parsed. A half-loaded effect log is worse than
    none: the run continues, the store answers lookups, and the answers are wrong for
    exactly the addresses whose records were dropped.
    """


class SnapshotVersionMismatch(SnapshotError):
    """A snapshot was written by a schema this build does not understand."""
