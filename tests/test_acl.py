from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from scripts.classify_corpus import (
    ManifestEntry,
    build_index,
    build_summary,
    classify_entries,
    load_manifest,
)

from helix.acl import (
    COMPANY_ROLES,
    DEFAULT_POLICY,
    DEFAULT_RULES,
    ENG_ROLES,
    SECURITY_ROLES,
    AclPolicy,
    Rule,
    normalize_role,
    normalize_roles,
)


def sample_path(prefix: str) -> str:
    return prefix if prefix.endswith(".md") else f"{prefix}/sample.md"


def test_every_default_rule_classifies_its_own_prefix() -> None:
    for rule in DEFAULT_RULES:
        decision = DEFAULT_POLICY.classify(rule.source, sample_path(rule.prefix))

        assert decision.classification == rule.classification
        assert decision.allowed_roles == rule.allowed_roles
        assert decision.rule_id == rule.id
        assert decision.matched_prefix == rule.prefix
        assert rule.prefix in decision.reason


@pytest.mark.parametrize(
    ("source", "path", "classification", "allowed", "denied"),
    [
        (
            "gitlab-docs",
            "doc/user/project/issues.md",
            "public:docs",
            "authenticated",
            "employee",
        ),
        (
            "handbook",
            "content/handbook/security/runbooks/incident.md",
            "restricted:security",
            "security",
            "engineer",
        ),
        (
            "handbook",
            "content/handbook/people-group/values.md",
            "confidential:hr",
            "hr",
            "finance",
        ),
        (
            "handbook",
            "content/handbook/finance/zuora.md",
            "confidential:finance",
            "finance",
            "hr",
        ),
        (
            "handbook",
            "content/handbook/legal/contracts.md",
            "confidential:legal",
            "legal",
            "finance",
        ),
        (
            "handbook",
            "content/handbook/engineering/architecture.md",
            "internal:eng",
            "engineer",
            "employee",
        ),
        (
            "handbook",
            "content/handbook/business-technology/zuora.md",
            "internal:company",
            "employee",
            "engineer",
        ),
        ("handbook", "content/handbook/unknown/page.md", "restricted:unknown", None, "admin"),
    ],
)
def test_role_matrix(
    source: str,
    path: str,
    classification: str,
    allowed: str | None,
    denied: str,
) -> None:
    decision = DEFAULT_POLICY.classify(source, path)

    assert decision.classification == classification
    assert not decision.allows([denied])
    if allowed is not None:
        assert decision.allows([allowed])
    else:
        assert decision.allowed_roles == ()
        assert not decision.allows(["admin", "security"])


def test_source_distinguishes_identical_paths() -> None:
    path = "doc/user/project/issues.md"
    assert DEFAULT_POLICY.classify("gitlab-docs", path).classification == "public:docs"
    assert DEFAULT_POLICY.classify("handbook", path).classification == "restricted:unknown"

    handbook_path = "content/handbook/security/incident.md"
    assert (
        DEFAULT_POLICY.classify("handbook", handbook_path).classification
        == "restricted:security"
    )
    assert (
        DEFAULT_POLICY.classify("gitlab-docs", handbook_path).classification
        == "restricted:unknown"
    )


def test_prefix_matching_is_boundary_safe() -> None:
    legal = DEFAULT_POLICY.classify(
        "handbook", "content/handbook/legal/contracts.md"
    )
    legalish = DEFAULT_POLICY.classify(
        "handbook", "content/handbook/legal-ops/contracts.md"
    )
    engineeringish = DEFAULT_POLICY.classify(
        "handbook", "content/handbook/engineering-notes/page.md"
    )

    assert legal.classification == "confidential:legal"
    assert legalish.classification == "restricted:unknown"
    assert engineeringish.classification == "restricted:unknown"

    exact = DEFAULT_POLICY.classify("handbook", "content/handbook/legal")
    assert exact.classification == "confidential:legal"


def test_longest_prefix_wins_over_table_order() -> None:
    broad = Rule(
        id="broad",
        source="handbook",
        prefix="content/handbook",
        classification="internal:company",
        allowed_roles=COMPANY_ROLES,
    )
    narrow = Rule(
        id="narrow",
        source="handbook",
        prefix="content/handbook/security",
        classification="restricted:security",
        allowed_roles=SECURITY_ROLES,
    )
    policy = AclPolicy((narrow, broad))

    decision = policy.classify("handbook", "content/handbook/security/runbook.md")

    assert decision.rule_id == "narrow"
    assert decision.classification == "restricted:security"
    assert decision.matched_prefix == "content/handbook/security"


def test_equal_prefixes_break_ties_by_rule_order() -> None:
    first = Rule(
        id="first",
        source="handbook",
        prefix="content/handbook/values",
        classification="internal:company",
        allowed_roles=COMPANY_ROLES,
    )
    second = Rule(
        id="second",
        source="handbook",
        prefix="content/handbook/values",
        classification="internal:eng",
        allowed_roles=ENG_ROLES,
    )
    policy = AclPolicy((first, second))

    assert policy.classify("handbook", "content/handbook/values/page.md").rule_id == "first"


def test_policy_rejects_duplicate_rule_ids() -> None:
    rule = Rule(
        id="same",
        source="handbook",
        prefix="content/handbook/a",
        classification="internal:company",
        allowed_roles=COMPANY_ROLES,
    )
    duplicate_id = Rule(
        id="same",
        source="handbook",
        prefix="content/handbook/b",
        classification="internal:company",
        allowed_roles=COMPANY_ROLES,
    )

    with pytest.raises(ValueError, match="Duplicate ACL rule id"):
        AclPolicy((rule, duplicate_id))


def test_unknown_path_denies_by_default() -> None:
    decision = DEFAULT_POLICY.classify("handbook", "content/handbook/mystery/page.md")

    assert decision.classification == "restricted:unknown"
    assert decision.allowed_roles == ()
    assert decision.rule_id == "acl-unknown-v1"
    assert decision.matched_prefix == ""
    assert "denied by default" in decision.reason
    assert not decision.allows(["admin", "security", "employee"])


def test_billing_is_an_alias_for_finance() -> None:
    assert normalize_role("billing") == "finance"
    assert normalize_role("finance") == "finance"
    assert normalize_roles(["billing", "finance"]) == frozenset({"finance"})

    decision = DEFAULT_POLICY.classify("handbook", "content/handbook/finance/zuora.md")
    assert decision.allows(["billing"])
    assert not decision.allows(["engineer"])

    with pytest.raises(ValueError, match="Unknown role: auditor"):
        normalize_role("auditor")


def test_decisions_are_deterministic_and_json_safe() -> None:
    first = DEFAULT_POLICY.classify("handbook", "content/handbook/legal/contracts.md")
    second = DEFAULT_POLICY.classify("handbook", "content/handbook/legal/contracts.md")

    assert first == second
    assert first.to_dict() == second.to_dict()
    json.dumps(first.to_dict())


def test_classify_entries_rejects_duplicate_source_path() -> None:
    entries = [
        ManifestEntry(source="handbook", path="content/handbook/legal/a.md"),
        ManifestEntry(source="handbook", path="content/handbook/legal/a.md"),
    ]

    with pytest.raises(ValueError, match="Duplicate ACL entry"):
        classify_entries(entries)


def test_index_and_summary_are_sorted_and_deterministic() -> None:
    entries = [
        ManifestEntry(source="handbook", path="content/handbook/security/b.md"),
        ManifestEntry(source="gitlab-docs", path="doc/user/a.md"),
        ManifestEntry(source="handbook", path="content/handbook/legal/a.md"),
    ]
    decisions = classify_entries(entries)

    index = build_index(decisions, "abc")
    summary = build_summary(decisions, "abc")

    assert index == build_index(list(reversed(decisions)), "abc")
    assert [entry["path"] for entry in index["entries"]] == [
        "doc/user/a.md",
        "content/handbook/legal/a.md",
        "content/handbook/security/b.md",
    ]
    assert summary["totals"] == {"documents": 3, "unknown": 0}
    assert summary["classifications"] == {
        "confidential:legal": 1,
        "public:docs": 1,
        "restricted:security": 1,
    }
    assert summary["sources"] == {"gitlab-docs": 1, "handbook": 2}
    assert "generated_at" not in summary


def test_load_manifest_reads_entries_and_hashes_bytes(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "name": "handbook",
                        "files": [{"path": "content/handbook/legal/a.md"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    manifest, entries, digest = load_manifest(manifest_path)

    assert manifest["sources"][0]["name"] == "handbook"
    assert entries == [
        ManifestEntry(source="handbook", path="content/handbook/legal/a.md")
    ]
    assert digest == hashlib.sha256(manifest_path.read_bytes()).hexdigest()


MANIFEST_PATH = Path("data/manifest.json")


@pytest.mark.skipif(not MANIFEST_PATH.is_file(), reason="corpus manifest not present")
def test_selected_corpus_has_zero_unknown_paths() -> None:
    _, entries, digest = load_manifest(MANIFEST_PATH)
    summary = build_summary(classify_entries(entries), digest)

    assert summary["totals"] == {"documents": 2_500, "unknown": 0}
    assert summary["classifications"] == {
        "confidential:finance": 19,
        "confidential:hr": 28,
        "confidential:legal": 28,
        "internal:company": 383,
        "internal:eng": 439,
        "public:docs": 1_500,
        "restricted:security": 103,
    }
