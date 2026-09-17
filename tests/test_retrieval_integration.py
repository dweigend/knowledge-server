from knowledge.knowledge_base.knowledge_service import Knowledge
from knowledge.knowledge_domain.knowledge_record_models import Claim
from knowledge.source_workflows.claim_reconciliation import claim_candidates


def test_main_retrieval_bounds_large_claim_sets_and_preserves_current_revisions(
    application: Knowledge,
) -> None:
    with application.database.transaction() as ledger:
        expected = ledger.append(
            "pilot",
            "claim",
            Claim(
                proposition="Immediate scores improved",
                scope="School population",
                qualifications="A limited trial",
            ),
            "human:fixture",
        )
        revised = ledger.append(
            "pilot",
            "claim",
            Claim(
                proposition="Immediate scores improved",
                scope="School population",
                qualifications="Retention not measured",
            ),
            "human:fixture",
            expected,
        )
        for number in range(45):
            ledger.append(
                "pilot",
                "claim",
                Claim(
                    proposition=f"Scores in unrelated test {number}",
                    scope="Another sample",
                    qualifications="A limited trial",
                ),
                "human:fixture",
            )
        unrelated = ledger.append(
            "pilot",
            "claim",
            Claim(
                proposition="Rainfall fell",
                scope="Coastal measurements",
                qualifications="Seasonal",
            ),
            "human:fixture",
        )

    candidates = claim_candidates(application, "pilot", "Immediate scores School population")
    assert len(candidates) == 40
    assert candidates[0].reference() == revised
    assert all(record.reference() not in [expected, unrelated] for record in candidates)
