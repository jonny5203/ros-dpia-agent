"""Deterministic DPIA screening rules."""

from __future__ import annotations

from typing import Final

from app.schemas.screening import (
    Art35TriggerId,
    Art35TriggerResult,
    CriterionStatus,
    DpiaConclusion,
    DpiaCriterionId,
    DpiaCriterionResult,
    DpiaScreeningInput,
    DpiaScreeningResult,
)

CRITERION_LABELS_NB: Final[dict[DpiaCriterionId, str]] = {
    DpiaCriterionId.EVALUATION: "Evaluering eller poengsetting",
    DpiaCriterionId.AUTOMATED_DECISION: (
        "Automatiske beslutninger med rettslig eller tilsvarende betydelig virkning"
    ),
    DpiaCriterionId.SYSTEMATIC_MONITORING: "Systematisk monitorering",
    DpiaCriterionId.SENSITIVE_DATA: (
        "Særlige kategorier eller opplysninger av svært personlig karakter"
    ),
    DpiaCriterionId.LARGE_SCALE: "Personopplysninger behandles i stor skala",
    DpiaCriterionId.DATASET_MATCHING: "Matching eller sammenstilling av datasett",
    DpiaCriterionId.VULNERABLE_SUBJECTS: ("Personopplysninger om sårbare registrerte"),
    DpiaCriterionId.NEW_TECHNOLOGY: ("Innovativ bruk eller anvendelse av ny teknologi"),
    DpiaCriterionId.RIGHT_OR_SERVICE: ("Behandlingen hindrer en rettighet, tjeneste eller avtale"),
}

ART35_LABELS_NB: Final[dict[Art35TriggerId, str]] = {
    Art35TriggerId.AUTOMATED_EVALUATION: (
        "Systematisk og omfattende automatisert evaluering med betydelig virkning"
    ),
    Art35TriggerId.LARGE_SCALE_SENSITIVE_DATA: (
        "Behandling i stor skala av særlige kategorier eller straffedata"
    ),
    Art35TriggerId.PUBLIC_AREA_MONITORING: (
        "Systematisk monitorering i stor skala av offentlig tilgjengelig område"
    ),
}

RATIONALE_NB: Final[dict[DpiaConclusion, str]] = {
    DpiaConclusion.REQUIRED: (
        "Basert på den dokumenterte informasjonen har prosjektet indikatorer "
        "som normalt krever en DPIA-vurdering. En personvernrådgiver må "
        "bekrefte konklusjonen."
    ),
    DpiaConclusion.LIKELY: (
        "Basert på den dokumenterte informasjonen har prosjektet indikatorer "
        "eller manglende dokumentasjon som tilsier at behovet for DPIA må "
        "vurderes nærmere. En personvernrådgiver må bekrefte konklusjonen."
    ),
    DpiaConclusion.NOT_INDICATED: (
        "Basert på den dokumenterte informasjonen er det ikke identifisert "
        "indikatorer som normalt tilsier DPIA. En personvernrådgiver må "
        "bekrefte vurderingen dersom behandlingen eller risikobildet endres."
    ),
}


def evaluate_dpia_screening(
    screening: DpiaScreeningInput,
) -> DpiaScreeningResult:
    """Apply the fixed DPIA truth table to verified assessments."""

    criteria_by_id = {assessment.id: assessment for assessment in screening.criteria}
    triggers_by_id = {assessment.id: assessment for assessment in screening.art35_3}

    criteria = [
        DpiaCriterionResult(
            id=criterion_id,
            label_nb=CRITERION_LABELS_NB[criterion_id],
            status=criteria_by_id[criterion_id].status,
            rationale=criteria_by_id[criterion_id].rationale,
            sourceReferences=criteria_by_id[criterion_id].sourceReferences,
        )
        for criterion_id in DpiaCriterionId
    ]

    art35_3 = [
        Art35TriggerResult(
            id=trigger_id,
            label_nb=ART35_LABELS_NB[trigger_id],
            status=triggers_by_id[trigger_id].status,
            rationale=triggers_by_id[trigger_id].rationale,
            sourceReferences=triggers_by_id[trigger_id].sourceReferences,
        )
        for trigger_id in Art35TriggerId
    ]

    criteria_count = sum(
        assessment.status is CriterionStatus.TRIGGERED for assessment in screening.criteria
    )
    art35_3_triggered = any(
        assessment.status is CriterionStatus.TRIGGERED for assessment in screening.art35_3
    )
    evidence_incomplete = any(
        assessment.status is CriterionStatus.INSUFFICIENT_EVIDENCE
        for assessment in [*screening.criteria, *screening.art35_3]
    )

    if art35_3_triggered or criteria_count >= 2:
        conclusion = DpiaConclusion.REQUIRED
    elif criteria_count == 1 or evidence_incomplete:
        conclusion = DpiaConclusion.LIKELY
    else:
        conclusion = DpiaConclusion.NOT_INDICATED

    return DpiaScreeningResult(
        criteria=criteria,
        art35_3=art35_3,
        criteria_count=criteria_count,
        art35_3_triggered=art35_3_triggered,
        conclusion=conclusion,
        evidence_incomplete=evidence_incomplete,
        requires_human_review=True,
        rationale_nb=RATIONALE_NB[conclusion],
    )
