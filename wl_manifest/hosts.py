"""Host selectors — `class` or `class/role`.

Host identity belongs to `wl-softrepo`, whose `docs/naming.md` defines
`<org>-<class><n>` and the rule that an institutionally licensed machine is
`wl-*` and a personal one is `wh-*`. This module restates only the class list,
because a selector cannot be parsed without it; everything else about hosts is
resolved against softrepo's contract rather than defined here (spec section
5.2).

The role segment exists because a rig is not one machine. `wl-rig-eye0` and
`wl-rig-sglx0` run different software while forming one system, so a package
may target `rig/sglx` and a stack query may ask about `rig` and mean all of
them. Extending softrepo's scheme to carry roles is a change set against that
repository, not a decision taken here.
"""

from __future__ import annotations

from dataclasses import dataclass

HOST_CLASSES: frozenset[str] = frozenset({"dws", "rws", "mws", "serv", "rig"})


@dataclass(frozen=True)
class HostSelector:
    klass: str
    role: str | None = None

    @classmethod
    def parse(cls, text: str) -> HostSelector:
        parts = text.split("/")
        if len(parts) > 2 or any(not p for p in parts):
            raise ValueError(f"malformed host selector: {text!r}")
        klass = parts[0]
        if klass not in HOST_CLASSES:
            raise ValueError(
                f"unknown host class {klass!r} in {text!r}; "
                f"wl-softrepo defines {sorted(HOST_CLASSES)}"
            )
        return cls(klass, parts[1] if len(parts) == 2 else None)

    def selects(self, target: HostSelector) -> bool:
        """Does this selector cover that target?

        A bare class covers every role within it; a role covers only itself.
        Asking for `rig` means every rig machine, asking for `rig/sglx` means
        one of them.
        """
        if self.klass != target.klass:
            return False
        return self.role is None or self.role == target.role

    def overlaps(self, other: HostSelector) -> bool:
        """Do these two describe any machine in common?

        Containment runs both ways and neither direction alone is right. A
        package declaring the bare class `rig` runs on every rig machine, so
        asking what `rig/sglx` needs must include it — yet `rig/sglx` does not
        *select* `rig`. Conversely a package declaring `rig/sglx` must appear
        when asking what the `rig` class needs collectively.

        This lives here, beside `selects`, because it is the same kind of
        thing: a relation between two selectors. It was written twice
        elsewhere before it was written once here.
        """
        return self.selects(other) or other.selects(self)

    def __str__(self) -> str:
        return self.klass if self.role is None else f"{self.klass}/{self.role}"
