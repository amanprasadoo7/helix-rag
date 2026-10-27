"""Deterministic source-and-path ACL classification.

The classifier labels a parsed document with a sensitivity classification and
the roles allowed to retrieve it. It deliberately does not look at content,
frontmatter, or tags: the reviewed policy is a table of source-aware path
prefixes, and anything unmatched is denied.

Matching is boundary-safe and longest-prefix first, so a future narrow rule can
override a broad one without reordering the table. Every decision records the
rule id, the matched prefix, and a human-readable reason for audit.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, cast

POLICY_VERSION = "acl-v1"
UNKNOWN_RULE_ID = "acl-unknown-v1"

Role = Literal[
    "authenticated",
    "employee",
    "engineer",
    "support",
    "hr",
    "finance",
    "legal",
    "security",
    "contractor",
    "admin",
]

Classification = Literal[
    "public:docs",
    "internal:eng",
    "internal:company",
    "restricted:security",
    "confidential:hr",
    "confidential:finance",
    "confidential:legal",
    "restricted:unknown",
]

ALL_ROLES: frozenset[Role] = frozenset(
    {
        "authenticated",
        "employee",
        "engineer",
        "support",
        "hr",
        "finance",
        "legal",
        "security",
        "contractor",
        "admin",
    }
)

ROLE_ALIASES: dict[str, Role] = {"billing": "finance"}

PUBLIC_ROLES: tuple[Role, ...] = ("authenticated",)
SECURITY_ROLES: tuple[Role, ...] = ("security", "admin")
HR_ROLES: tuple[Role, ...] = ("hr", "legal", "security", "admin")
FINANCE_ROLES: tuple[Role, ...] = ("finance", "legal", "security", "admin")
LEGAL_ROLES: tuple[Role, ...] = ("legal", "security", "admin")
ENG_ROLES: tuple[Role, ...] = ("engineer", "support", "security", "admin")
COMPANY_ROLES: tuple[Role, ...] = ("employee", "admin")


def normalize_role(role: str) -> Role:
    """Return the canonical ACL role, resolving aliases such as ``billing``."""
    canonical = ROLE_ALIASES.get(role, role)
    if canonical not in ALL_ROLES:
        raise ValueError(f"Unknown role: {role}")
    return cast(Role, canonical)


def normalize_roles(roles: Iterable[str]) -> frozenset[Role]:
    """Canonicalize a user's roles; duplicates collapse into a set."""
    return frozenset(normalize_role(role) for role in roles)


@dataclass(frozen=True)
class Rule:
    """One reviewed path rule for one source."""

    id: str
    source: str
    prefix: str
    classification: Classification
    allowed_roles: tuple[Role, ...]

    def matches(self, path: str) -> bool:
        """Boundary-safe match: a prefix matches itself or a child path."""
        return path == self.prefix or path.startswith(f"{self.prefix}/")


@dataclass(frozen=True)
class AclDecision:
    """The classification and authorization metadata for one document."""

    source: str
    path: str
    classification: Classification
    allowed_roles: tuple[Role, ...]
    rule_id: str
    matched_prefix: str
    reason: str

    def allows(self, user_roles: Iterable[str]) -> bool:
        """Allow if the user's canonical roles intersect the allow list."""
        return bool(normalize_roles(user_roles).intersection(self.allowed_roles))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "path": self.path,
            "classification": self.classification,
            "allowed_roles": list(self.allowed_roles),
            "rule_id": self.rule_id,
            "matched_prefix": self.matched_prefix,
            "reason": self.reason,
        }


def _rule(
    rule_id: str,
    source: str,
    prefix: str,
    classification: Classification,
    roles: tuple[Role, ...],
) -> Rule:
    return Rule(
        id=rule_id,
        source=source,
        prefix=prefix,
        classification=classification,
        allowed_roles=roles,
    )


DEFAULT_RULES: tuple[Rule, ...] = (
    _rule(
        "acl-path-docs-v1",
        "gitlab-docs",
        "doc",
        "public:docs",
        PUBLIC_ROLES,
    ),
    _rule(
        "acl-path-security-v1",
        "handbook",
        "content/handbook/security",
        "restricted:security",
        SECURITY_ROLES,
    ),
    _rule(
        "acl-path-hr-people-group-v1",
        "handbook",
        "content/handbook/people-group",
        "confidential:hr",
        HR_ROLES,
    ),
    _rule(
        "acl-path-hr-people-policies-v1",
        "handbook",
        "content/handbook/people-policies",
        "confidential:hr",
        HR_ROLES,
    ),
    _rule(
        "acl-path-hr-hiring-v1",
        "handbook",
        "content/handbook/hiring",
        "confidential:hr",
        HR_ROLES,
    ),
    _rule(
        "acl-path-hr-total-rewards-v1",
        "handbook",
        "content/handbook/total-rewards",
        "confidential:hr",
        HR_ROLES,
    ),
    _rule(
        "acl-path-hr-labor-notices-v1",
        "handbook",
        "content/handbook/labor-and-employment-notices",
        "confidential:hr",
        HR_ROLES,
    ),
    _rule(
        "acl-path-finance-v1",
        "handbook",
        "content/handbook/finance",
        "confidential:finance",
        FINANCE_ROLES,
    ),
    _rule(
        "acl-path-acquisitions-v1",
        "handbook",
        "content/handbook/acquisitions",
        "confidential:finance",
        FINANCE_ROLES,
    ),
    _rule(
        "acl-path-legal-v1",
        "handbook",
        "content/handbook/legal",
        "confidential:legal",
        LEGAL_ROLES,
    ),
    _rule(
        "acl-path-board-meetings-v1",
        "handbook",
        "content/handbook/board-meetings",
        "confidential:legal",
        LEGAL_ROLES,
    ),
    _rule(
        "acl-path-engineering-v1",
        "handbook",
        "content/handbook/engineering",
        "internal:eng",
        ENG_ROLES,
    ),
    _rule(
        "acl-path-support-v1",
        "handbook",
        "content/handbook/support",
        "internal:eng",
        ENG_ROLES,
    ),
    _rule(
        "acl-path-product-v1",
        "handbook",
        "content/handbook/product",
        "internal:eng",
        ENG_ROLES,
    ),
    _rule(
        "acl-path-product-development-v1",
        "handbook",
        "content/handbook/product-development",
        "internal:eng",
        ENG_ROLES,
    ),
    _rule(
        "acl-path-solutions-architects-v1",
        "handbook",
        "content/handbook/solutions-architects",
        "internal:eng",
        ENG_ROLES,
    ),
    _rule(
        "acl-path-it-v1",
        "handbook",
        "content/handbook/it",
        "internal:eng",
        ENG_ROLES,
    ),
    _rule(
        "acl-path-tools-and-tips-v1",
        "handbook",
        "content/handbook/tools-and-tips",
        "internal:eng",
        ENG_ROLES,
    ),
    _rule(
        "acl-path-marketing-v1",
        "handbook",
        "content/handbook/marketing",
        "internal:company",
        COMPANY_ROLES,
    ),
    _rule(
        "acl-path-sales-v1",
        "handbook",
        "content/handbook/sales",
        "internal:company",
        COMPANY_ROLES,
    ),
    _rule(
        "acl-path-customer-experience-v1",
        "handbook",
        "content/handbook/customer-experience",
        "internal:company",
        COMPANY_ROLES,
    ),
    _rule(
        "acl-path-eta-v1",
        "handbook",
        "content/handbook/eta",
        "internal:company",
        COMPANY_ROLES,
    ),
    _rule(
        "acl-path-company-v1",
        "handbook",
        "content/handbook/company",
        "internal:company",
        COMPANY_ROLES,
    ),
    _rule(
        "acl-path-leadership-v1",
        "handbook",
        "content/handbook/leadership",
        "internal:company",
        COMPANY_ROLES,
    ),
    _rule(
        "acl-path-communication-v1",
        "handbook",
        "content/handbook/communication",
        "internal:company",
        COMPANY_ROLES,
    ),
    _rule(
        "acl-path-upstream-studios-v1",
        "handbook",
        "content/handbook/upstream-studios",
        "internal:company",
        COMPANY_ROLES,
    ),
    _rule(
        "acl-path-enterprise-data-v1",
        "handbook",
        "content/handbook/enterprise-data",
        "internal:company",
        COMPANY_ROLES,
    ),
    _rule(
        "acl-path-resellers-v1",
        "handbook",
        "content/handbook/resellers",
        "internal:company",
        COMPANY_ROLES,
    ),
    _rule(
        "acl-path-about-v1",
        "handbook",
        "content/handbook/about",
        "internal:company",
        COMPANY_ROLES,
    ),
    _rule(
        "acl-path-entity-v1",
        "handbook",
        "content/handbook/entity",
        "internal:company",
        COMPANY_ROLES,
    ),
    _rule(
        "acl-path-values-v1",
        "handbook",
        "content/handbook/values",
        "internal:company",
        COMPANY_ROLES,
    ),
    _rule(
        "acl-path-business-technology-v1",
        "handbook",
        "content/handbook/business-technology",
        "internal:company",
        COMPANY_ROLES,
    ),
    _rule(
        "acl-path-handbook-root-v1",
        "handbook",
        "content/handbook/_index.md",
        "internal:company",
        COMPANY_ROLES,
    ),
)


@dataclass(frozen=True)
class AclPolicy:
    """An ordered, source-aware rule table."""

    rules: tuple[Rule, ...] = DEFAULT_RULES
    policy_version: str = POLICY_VERSION

    def __post_init__(self) -> None:
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate ACL rule id")

    def match(self, source: str, path: str) -> Rule | None:
        """Return the longest matching rule, breaking ties by table order."""
        candidates = [
            (index, rule)
            for index, rule in enumerate(self.rules)
            if rule.source == source and rule.matches(path)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: (len(item[1].prefix), -item[0]))[1]

    def classify(self, source: str, path: str) -> AclDecision:
        """Classify one document, denying unknown paths."""
        rule = self.match(source, path)
        if rule is None:
            return AclDecision(
                source=source,
                path=path,
                classification="restricted:unknown",
                allowed_roles=(),
                rule_id=UNKNOWN_RULE_ID,
                matched_prefix="",
                reason=f"no rule matched source={source} path={path}; denied by default",
            )
        return AclDecision(
            source=source,
            path=path,
            classification=rule.classification,
            allowed_roles=rule.allowed_roles,
            rule_id=rule.id,
            matched_prefix=rule.prefix,
            reason=f"source={source} path starts with {rule.prefix}",
        )


DEFAULT_POLICY = AclPolicy()
