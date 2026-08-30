"""The Necessity Ledger — is the model earning its cost?

Every agent project asserts that its LLM is essential. Almost none can produce the number,
and the reason is uncomfortable: measuring it honestly means running the model against your
own cache and publishing how often it agreed. A system that agrees with itself 98% of the
time has just proved that 98% of its workload is a lookup table.

This project reports that number as a product surface rather than a footnote, because the
alternative — asserting necessity and never testing it — is exactly what an earlier version
of this codebase did, and a twelve-line rule table beat it.

    decisions served          how many answers the fleet gave
      from the table (free)   answers that cost nothing
      from the model (paid)   answers that cost money
    shadow samples            answers re-derived deliberately to check the table
      agreed                  the table was right; the model added nothing here
      DISAGREED               the table was wrong; this is where the model earned its fee

    REASONING NECESSITY       the disagreement rate

Necessity is the share of sampled decisions where the model changed the answer. It is
deliberately not the share of traffic that hit the model — that number measures cache
warmth, flatters the system, and answers a question nobody asked.

The honest reading cuts both ways, and both are stated in the output. A low necessity means
most of the workload is a table and should be served as one: that is a cost result, not a
failure. A high necessity means the situations are genuinely novel and the model is
load-bearing. Either way the number is measured continuously instead of claimed once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from policy.shadow import ShadowReport
from policy.table import PolicyTable


@dataclass
class NecessityLedger:
    """Decisions served, what they cost, and how much of it the model was needed for."""

    served_from_table: int = 0
    # Decisions the table could not answer. Not the same as calls made: a decision that
    # *would* need the model is only a call once someone pays for it, and conflating the
    # two made the cost projection divide by a number 28 times too large.
    served_from_model: int = 0
    model_calls_made: int = 0
    model_cost_usd: float = 0.0
    shadow: ShadowReport | None = None
    policy_version: str = ""
    period: str = "this run"

    @property
    def decisions(self) -> int:
        return self.served_from_table + self.served_from_model

    @property
    def table_share(self) -> float:
        return self.served_from_table / self.decisions if self.decisions else 0.0

    @property
    def necessity(self) -> float:
        """Share of shadow samples where the model disagreed with the table.

        nan when nothing was sampled, and the report says so in words. Printing 0.0%
        necessity because no check was run would be a claim of perfect cache accuracy
        derived from having never looked.
        """
        return self.shadow.drift_rate if self.shadow else float("nan")

    @property
    def calls_paid_for(self) -> int:
        """Model calls actually executed, which is what the cost was divided among."""
        return self.model_calls_made + (self.shadow.sampled if self.shadow else 0)

    @property
    def cost_per_call(self) -> float:
        return self.total_cost() / self.calls_paid_for if self.calls_paid_for else 0.0

    def projected_naive_cost(self) -> float:
        """What the same decisions would have cost at one model call apiece.

        Derived from the cost of calls genuinely made, never from decisions that merely
        would have needed one. A projection, never a measurement, and labelled as such
        wherever it is printed.
        """
        return self.cost_per_call * self.decisions

    def total_cost(self) -> float:
        return self.model_cost_usd + (self.shadow.cost_usd if self.shadow else 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "policy_version": self.policy_version,
            "decisions": self.decisions,
            "served_from_table": self.served_from_table,
            "served_from_model": self.served_from_model,
            "model_calls_made": self.model_calls_made,
            "cost_per_call_usd": round(self.cost_per_call, 6),
            "table_share": round(self.table_share, 4),
            "necessity": self.necessity,
            "cost_usd": round(self.total_cost(), 4),
            "projected_naive_cost_usd": round(self.projected_naive_cost(), 2),
            "shadow": self.shadow.to_dict() if self.shadow else None,
        }

    def render(self, table: PolicyTable | None = None) -> str:
        """The report, as a CFO would want to read it."""
        w = 58
        lines = [
            "",
            f"  NECESSITY LEDGER{'':<12}{self.period:>28}",
            f"  {'─' * w}",
            f"  {'decisions served':<40}{self.decisions:>18,}",
        ]
        if self.decisions:
            lines += [
                f"    {'from policy table (free)':<38}"
                f"{self.served_from_table:>13,}{100 * self.table_share:>6.2f}%",
                f"    {'needing the model':<38}{self.served_from_model:>13,}"
                f"{100 * (1 - self.table_share):>6.2f}%",
            ]
        if self.shadow and self.shadow.sampled:
            s = self.shadow
            agreed = 100 * s.confirmed / s.sampled
            lines += [
                f"  {'shadow samples':<40}{s.sampled:>18,}",
                f"    {'model agreed with table':<38}{s.confirmed:>13,}{agreed:>6.2f}%",
                f"    {'model DISAGREED → rows invalidated':<38}"
                f"{s.drifted:>13,}{100 * s.drift_rate:>6.2f}%",
            ]
            if s.failed:
                lines.append(
                    f"    {'sample failed → counted, not confirmed':<38}{s.failed:>13,}"
                )
            lines += [
                f"  {'─' * w}",
                f"  {'REASONING NECESSITY':<40}{100 * s.drift_rate:>17.2f}%",
                f"    → {100 * (1 - s.drift_rate):.2f}% of this workload is a lookup table.",
                f"    → the remaining {100 * s.drift_rate:.2f}% is where the model is",
                f"      load-bearing, and it is the only part paid at full price.",
            ]
        else:
            lines += [
                f"  {'─' * w}",
                "  REASONING NECESSITY                              not measured",
                "    → no shadow samples were taken, so nothing is known about",
                "      whether the table is still right. This is not 0%.",
            ]
        naive = self.projected_naive_cost()
        lines += [
            f"  {'─' * w}",
            f"  {'model calls actually paid for':<40}{self.calls_paid_for:>18,}",
            f"  {'cost this period':<40}{'$' + format(self.total_cost(), ',.4f'):>18}",
            f"  {'cost without the kernel':<40}"
            f"{'$' + format(naive, ',.2f'):>18}  ← projected",
        ]
        if table is not None:
            lines.append(
                f"  {'policy':<40}"
                f"{f'v{table.version} · {table.populated:,}/{table.ceiling:,} cells':>18}"
            )
        lines.append("")
        return "\n".join(lines)
