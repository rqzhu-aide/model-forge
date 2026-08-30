"""Backend-owned researcher projections assembled from formal records."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from ..api.models import (
    ActionDescriptor,
    ArtifactLink,
    AttentionSummary,
    AvailableAction,
    ContextOption,
    CurrentRecordView,
    DecisionBrief,
    EvidenceLink,
    EvidenceSummary,
    LiteratureGapSummary,
    MethodIdentity as ApiMethodIdentity,
    MethodEvaluation,
    MethodRow,
    PhaseNavigationSummary,
    PhaseView,
    ProjectionStamp,
    ProjectBriefView,
    ProjectOverview,
    ProjectStorageView,
    ProjectSummary,
    RunConfigurationView,
    RunSummary,
    ScientificStatus,
)
from ..contracts import PhaseContractRepository
from ..domain.identities import MethodIdentity
from ..domain.identities import PHASE_IDS
from ..projections import build_phase_configuration
from ..storage.repository import HubRepository
from .repository_views import RepositoryQueries, row_json


ACTIVE_RUN_STATES = {
    "created",
    "preparing",
    "prepared",
    "running",
    "cancellation_requested",
    "submitted",
    "validating",
    "promoting",
}


def project_summary(
    row: sqlite3.Row,
    *,
    active_run_count: int,
    brief_payload: dict[str, Any] | None = None,
) -> ProjectSummary:
    payload = row_json(row)
    brief = brief_payload or payload
    return ProjectSummary(
        project_id=str(row["project_id"]),
        name=str(payload["name"]),
        research_question=str(brief["research_question"]),
        domains=[str(item) for item in brief.get("domains", [])],
        updated_at=str(row["updated_at"]),
        active_run_count=active_run_count,
    )


class ResearchProjectionService:
    def __init__(
        self,
        repository: HubRepository,
        phases: PhaseContractRepository,
        *,
        execution_available: bool,
    ) -> None:
        self.repository = repository
        self.queries = RepositoryQueries(repository)
        self.phases = phases
        self.execution_available = execution_available

    def list_methods(self, project_id: str) -> list[MethodRow]:
        project = self.repository.get_project(project_id)
        active_run_exists = any(
            row["status"] in ACTIVE_RUN_STATES
            for row in self.queries.list_runs(project_id)
        )
        catalog = self.repository.get_current_record(
            project_id, "p2.method_catalog.current"
        )
        records = [
            row
            for row in self.repository.list_current_records(project_id)
            if row["record_type"] == "method_record"
        ]
        result: list[MethodRow] = []
        for row in records:
            payload = row_json(row)
            raw_identity = payload.get("identity") or payload.get("method_identity")
            if type(raw_identity) is not dict:
                continue
            identity = MethodIdentity.from_dict(raw_identity)
            lifecycle = str(payload.get("lifecycle_state", "proposed"))
            if lifecycle not in {"proposed", "active", "retired"}:
                lifecycle = "proposed"
            mathematical = payload.get("mathematical_definition", {})
            definition_summary = _mathematical_summary(mathematical)
            assumptions = payload.get("assumptions", [])
            assumption_text = [
                str(item.get("statement", "")) if type(item) is dict else str(item)
                for item in assumptions
            ]
            action_type = (
                "reactivate_method"
                if lifecycle == "retired"
                else ("activate_method" if lifecycle == "proposed" else "retire_method")
            )
            result.append(
                MethodRow(
                    identity=ApiMethodIdentity.model_validate(identity.to_dict()),
                    display_name=str(payload.get("title", identity.stable_id)),
                    aliases=[str(item) for item in payload.get("aliases", [])] or None,
                    lifecycle_state=lifecycle,
                    summary=str(payload.get("summary", "")),
                    mathematical_summary=definition_summary,
                    definition_artifact=ArtifactLink(
                        artifact_id=str(row["artifact_id"]),
                        label="Complete structured method definition",
                        information_layer="structured",
                        media_type="application/json",
                        href=(
                            f"/api/v1/projects/{project_id}/artifacts/"
                            f"{row['artifact_id']}"
                        ),
                    ),
                    assumptions=assumption_text or None,
                    provenance_summary=_provenance_summary(payload),
                    novelty_summary=str(payload.get("rationale", "")) or None,
                    evaluation=_method_evaluation(payload),
                    feasibility_summary=str(payload.get("feasibility_summary", "")) or None,
                    principal_risks=[str(item) for item in payload.get("limitations", [])] or None,
                    phase_statuses=self._method_phase_statuses(project_id, identity),
                    actions=[
                        ActionDescriptor(
                            descriptor_id=_action_id(
                                project_id,
                                str(identity.stable_id),
                                str(identity.version),
                                str(identity.definition_sha256),
                                str(row["generation_id"]),
                                str(catalog["generation_id"]) if catalog is not None else "none",
                                str(project["authority_root_sha256"]),
                                action_type,
                            ),
                            action_type=action_type,
                            execution_kind="control_transaction",
                            enabled=(
                                lifecycle in {"proposed", "active", "retired"}
                                and not active_run_exists
                                and catalog is not None
                            ),
                            reason_code=(
                                None
                                if (
                                    lifecycle in {"proposed", "active", "retired"}
                                    and not active_run_exists
                                    and catalog is not None
                                )
                                else (
                                    "control.active_run"
                                    if active_run_exists
                                    else "method.catalog_missing"
                                )
                            ),
                            researcher_message=(
                                None
                                if (
                                    lifecycle in {"proposed", "active", "retired"}
                                    and not active_run_exists
                                    and catalog is not None
                                )
                                else (
                                    "Wait for active research runs to finish or cancel "
                                    "them before changing the method portfolio."
                                    if active_run_exists
                                    else "A current Phase 2 method catalog is required."
                                )
                            ),
                            consequence_summary=(
                                "Change portfolio lifecycle without changing the mathematical "
                                "method identity or starting a research run."
                            ),
                            method_identity=ApiMethodIdentity.model_validate(identity.to_dict()),
                            method_id=str(identity.stable_id),
                            target_id=str(row["generation_id"]),
                            requires_reason=True,
                        )
                    ],
                )
            )
        return sorted(result, key=lambda item: item.display_name.casefold())

    def phase_view(
        self,
        project_id: str,
        phase_id: str,
        *,
        mode: str | None,
        method_id: str | None,
        active_runs: Sequence[RunSummary],
        recent_runs: Sequence[RunSummary],
        role_resources: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> PhaseView:
        document = self.phases.contract_document(phase_id)
        modes = tuple(document["run_modes"])
        selected_mode = mode or str(modes[0]["mode_id"])
        mode_document = next(
            (item for item in modes if item["mode_id"] == selected_mode), None
        )
        if mode_document is None:
            raise ValueError(f"Unknown phase mode {selected_mode!r}.")
        selected_method_row = self._selected_method_row(project_id, method_id)
        selected_method = (
            MethodIdentity.from_dict(selected_method_row.identity.model_dump())
            if selected_method_row is not None
            else None
        )
        current_options, findings = self._current_input_options(
            project_id,
            document,
            selected_mode,
            selected_method,
            phase_id,
        )
        if (
            phase_id in {"P3", "P4", "P5"}
            and selected_method_row is not None
            and selected_method_row.lifecycle_state != "active"
        ):
            findings.insert(
                0,
                {
                    "code": "method.not_active",
                    "message": (
                        "Select an active current method before starting this phase."
                    ),
                },
            )
        if not self.execution_available:
            findings.append(
                {
                    "code": "executor.unavailable",
                    "message": (
                        "No role executor is configured for this server. "
                        "Start the server with MODEL_FORGE_EXECUTOR_KIND=fake "
                        "(development) or hermes_kanban to enable runs."
                    ),
                }
            )
        projected = build_phase_configuration(
            repository=self.phases,
            project_id=project_id,
            phase_id=phase_id,
            selected_mode=selected_mode,
            selected_method=selected_method,
            current_inputs=current_options,
            history_options=self._history_options(
                project_id, phase_id, selected_method, document
            ),
            eligibility_findings=findings,
            authority_head={
                "authority_sequence": int(
                    self.repository.get_project(project_id)["authority_sequence"]
                ),
                "authority_root_sha256": str(
                    self.repository.get_project(project_id)["authority_root_sha256"]
                ),
                "current_revision": int(
                    self.repository.get_project(project_id)["current_revision"]
                ),
            },
            role_resources=role_resources,
        )
        current = (
            None
            if phase_id in {"P3", "P4", "P5"} and selected_method is None
            else self._phase_current_record(project_id, phase_id, selected_method)
        )
        component_rows = (
            []
            if phase_id in {"P3", "P4", "P5"} and selected_method is None
            else _phase_rows(
                self.repository.list_current_records(project_id),
                phase_id,
                selected_method,
            )
        )
        artifacts = [
            ArtifactLink(
                artifact_id=str(row["artifact_id"]),
                label=str(
                    row_json(row).get(
                        "title",
                        str(row["record_type"]).replace("_", " ").title(),
                    )
                ),
                information_layer="structured",
                media_type="application/json",
                href=(
                    f"/api/v1/projects/{project_id}/artifacts/"
                    f"{row['artifact_id']}"
                ),
            )
            for row in component_rows
        ]
        current_view = None
        if current is not None:
            payload = row_json(current)
            current_view = CurrentRecordView(
                record_id=str(payload.get("record_id", current["generation_id"])),
                generation_id=str(current["generation_id"]),
                title=str(payload.get("title", document["name"])),
                summary=_record_summary(payload),
                source_run_id=str(current["source_run_id"] or "run.project_bootstrap"),
                published_at=str(current["published_at"]),
                method_identity=(
                    ApiMethodIdentity.model_validate(selected_method.to_dict())
                    if selected_method is not None
                    else None
                ),
                basis_summary=str(payload.get("basis_summary", "Current formal basis.")),
                change_summary=str(payload.get("change_summary", "")),
                status=self._record_status(
                    payload,
                    published_at=str(current["published_at"]),
                    method_bound=selected_method is not None,
                    attention_items=self._attention_items(
                        project_id,
                        phase_id=phase_id,
                        method=selected_method,
                    ),
                ),
            )
        action_models = [ActionDescriptor.model_validate(item) for item in projected.pop("actions")]
        descriptor_basis = projected.pop("_descriptor_basis", None)
        return PhaseView(
            phase_id=phase_id,
            name=str(document["name"]),
            purpose=str(document["scientific_purpose"]),
            current_record=current_view,
            assessment=(
                current_view.status
                if current_view is not None
                else ScientificStatus(
                    record_position="none",
                    alignment="unassessed",
                    attention="none",
                    scientific_outcome="not_assessed",
                )
            ),
            decision_brief=self._decision_brief(
                project_id, phase_id, selected_method
            ),
            evidence=self._evidence(project_id, phase_id, selected_method),
            artifacts=artifacts,
            run_configuration=RunConfigurationView.model_validate(projected),
            actions=action_models,
            active_runs=list(active_runs),
            recent_runs=list(recent_runs),
            descriptor_basis=descriptor_basis,
            projection=self._projection(project_id),
            literature_gaps=(
                self._literature_gaps(project_id) if phase_id == "P1" else []
            ),
            empty_state_message=(
                None
                if current_view is not None
                else "No formal result has been published for this selection."
            ),
        )

    def overview(
        self,
        project_id: str,
        *,
        active_runs: Sequence[RunSummary],
    ) -> ProjectOverview:
        project_row = self.repository.get_project(project_id)
        methods = self.list_methods(project_id)
        phase_one = self._phase_current_record(project_id, "P1", None)
        literature = None
        if phase_one is not None:
            payload = row_json(phase_one)
            from ..api.models import LiteratureSummary

            literature = LiteratureSummary(
                source_count=len(
                    self.repository.list_collection_items(
                        project_id, "p1.literature_sources"
                    )
                ),
                coverage_summary=str(payload.get("coverage_summary", "")),
                current_synthesis=_record_summary(payload),
                status=ScientificStatus(
                    publication_state="formal",
                    record_position="current",
                    alignment="not_applicable",
                    scientific_outcome=_outcome(payload),
                    last_published_at=str(phase_one["published_at"]),
                ),
            )
        brief = self.project_brief(
            project_id, active_run_count=len(active_runs)
        )
        brief_row = self.repository.get_current_record(
            project_id, "project.brief.current"
        )
        assert brief_row is not None
        attention = self._attention_items(
            project_id, phase_id=None, method=None
        )
        return ProjectOverview(
            project=project_summary(
                project_row,
                active_run_count=len(active_runs),
                brief_payload=row_json(brief_row),
            ),
            project_brief=brief,
            literature_summary=literature,
            methods=methods,
            phases=self._phase_navigation(project_id, active_runs),
            active_runs=list(active_runs),
            attention_items=attention,
            storage=ProjectStorageView(
                explanation=(
                    "Formal project state is stored in backend-managed SQLite and "
                    "content-addressed storage. This version has no isolated physical "
                    "project folder that can be opened safely."
                )
            ),
            actions=[],
            projection=self._projection(project_id),
        )

    def project_brief(
        self,
        project_id: str,
        *,
        active_run_count: int,
    ) -> ProjectBriefView:
        row = self.repository.get_current_record(
            project_id, "project.brief.current"
        )
        if row is None:
            raise ValueError("The project has no current formal project brief.")
        payload = row_json(row)
        enabled = active_run_count == 0
        action = ActionDescriptor(
            descriptor_id=_action_id(
                project_id,
                str(row["generation_id"]),
                str(self.repository.get_project(project_id)["authority_root_sha256"]),
                "update_project_brief",
            ),
            action_type="update_project_brief",
            execution_kind="configuration",
            enabled=enabled,
            reason_code=None if enabled else "control.active_run",
            researcher_message=(
                None
                if enabled
                else (
                    "Wait for active research runs to finish or cancel them before "
                    "changing the formal project brief."
                )
            ),
            consequence_summary=(
                "Replace the formal project brief and preserve the earlier brief "
                "as immutable history. No research run or role execution will start."
            ),
            target_id=str(row["generation_id"]),
            requires_reason=True,
        )
        artifact_id = str(row["artifact_id"])
        return ProjectBriefView(
            project_id=project_id,
            record_id=str(payload.get("record_id", row["generation_id"])),
            generation_id=str(row["generation_id"]),
            research_question=str(payload["research_question"]),
            domains=[str(item) for item in payload.get("domains", [])],
            intended_use=str(payload["intended_use"]),
            scope=(
                str(payload["scope"])
                if type(payload.get("scope")) is str
                else None
            ),
            decision_criteria=[
                str(item) for item in payload.get("decision_criteria", [])
            ],
            constraints=[str(item) for item in payload.get("constraints", [])],
            scope_note=str(payload.get("scope_note", "")),
            published_at=str(row["published_at"]),
            artifact=ArtifactLink(
                artifact_id=artifact_id,
                label="Formal project brief",
                information_layer="structured",
                media_type="application/json",
                href=f"/api/v1/projects/{project_id}/artifacts/{artifact_id}",
            ),
            actions=[action],
            projection=self._projection(project_id),
        )

    def _phase_navigation(
        self,
        project_id: str,
        active_runs: Sequence[RunSummary],
    ) -> list[PhaseNavigationSummary]:
        current = self.repository.list_current_records(project_id)
        summaries: list[PhaseNavigationSummary] = []
        for phase_id in sorted(PHASE_IDS):
            rows = _phase_rows(current, phase_id, None)
            phase_runs = [run for run in active_runs if run.phase == phase_id]
            phase_attention = self._attention_items(
                project_id, phase_id=phase_id, method=None
            )
            statuses = [
                self._record_status(
                    row_json(row),
                    published_at=str(row["published_at"]),
                    method_bound=phase_id in {"P3", "P4", "P5"},
                    attention_items=(),
                )
                for row in rows
            ]
            assessment = _aggregate_status(statuses).model_copy(
                update={
                    "attention": _attention_level(phase_attention),
                    "attention_count": len(phase_attention),
                }
            )
            latest = max(
                (str(row["published_at"]) for row in rows),
                default=None,
            )
            method_ids = {
                str(method.stable_id)
                for method in (_payload_method(row_json(row)) for row in rows)
                if method is not None
            }
            if phase_runs:
                navigation_state = "active_run"
                summary = (
                    f"{len(phase_runs)} user-started run(s) are active. "
                    f"{len(rows)} current formal record(s) remain available."
                )
            elif assessment.attention not in {None, "none"}:
                navigation_state = "attention_required"
                summary = (
                    f"{len(rows)} current formal record(s) are available with "
                    f"{len(phase_attention)} open research question(s)."
                )
            elif rows:
                navigation_state = "current_records"
                summary = f"{len(rows)} current formal record(s) are available."
            else:
                navigation_state = "no_current_record"
                summary = "No current formal record is available for this phase."
            document = self.phases.contract_document(phase_id)
            summaries.append(
                PhaseNavigationSummary(
                    phase_id=phase_id,
                    name=str(document["name"]),
                    navigation_state=navigation_state,
                    formal_record_count=len(rows),
                    method_scoped_record_count=len(method_ids),
                    active_run_count=len(phase_runs),
                    latest_published_at=latest,
                    assessment=assessment,
                    summary=summary,
                )
            )
        return summaries

    def _attention_items(
        self,
        project_id: str,
        *,
        phase_id: str | None,
        method: MethodIdentity | None,
    ) -> list[AttentionSummary]:
        run_phases: dict[str, str] = {}
        run_methods: dict[str, MethodIdentity] = {}
        for run in self.queries.list_runs(project_id):
            payload = row_json(run)
            run_id = str(run["run_id"])
            if type(payload.get("phase")) is str:
                run_phases[run_id] = str(payload["phase"])
            run_method = _payload_method(payload)
            if run_method is not None:
                run_methods[run_id] = run_method
        result: list[AttentionSummary] = []
        for row in self.repository.list_collection_items(
            project_id, "project.attention_history"
        ):
            payload = row_json(row)
            if str(payload.get("disposition", "open")) != "open":
                continue
            source_run_id = str(
                row["source_run_id"] or payload.get("source_run_id", "")
            )
            item_phase = payload.get("phase")
            if type(item_phase) is not str:
                item_phase = run_phases.get(source_run_id)
            if phase_id is not None and item_phase != phase_id:
                continue
            item_method = _payload_method(payload) or run_methods.get(source_run_id)
            if (
                method is not None
                and item_method is not None
                and item_method != method
            ):
                continue
            severity = str(payload.get("severity", "informational"))
            if severity not in {
                "informational",
                "monitor",
                "reassessment_required",
                "blocking",
            }:
                severity = "informational"
            attention_id = str(
                payload.get("attention_id", row["item_id"])
            )
            result.append(
                AttentionSummary(
                    attention_id=attention_id,
                    severity=severity,
                    question=str(payload.get("question", "Open research question")),
                    phase=item_phase if item_phase in PHASE_IDS else None,
                    method_id=(
                        str(item_method.stable_id)
                        if item_method is not None
                        else None
                    ),
                )
            )
        return result

    def _literature_gaps(self, project_id: str) -> list[LiteratureGapSummary]:
        """Collect open LITERATURE_GAP attention items for P1 re-run recommendations.

        Scans ``project.attention_history`` for items whose ``question``
        field starts with ``LITERATURE_GAP:``. An item is considered
        *addressed* (and therefore excluded) when a Phase 1 publication
        occurred after the item was appended — this is a read-time
        computation, so no mutation of immutable collection items is
        needed.
        """
        p1_published_at = self._latest_p1_publication_time(project_id)
        run_phases: dict[str, str] = {}
        run_methods: dict[str, MethodIdentity] = {}
        for run in self.queries.list_runs(project_id):
            payload = row_json(run)
            run_id = str(run["run_id"])
            if type(payload.get("phase")) is str:
                run_phases[run_id] = str(payload["phase"])
            run_method = _payload_method(payload)
            if run_method is not None:
                run_methods[run_id] = run_method
        result: list[LiteratureGapSummary] = []
        for row in self.repository.list_collection_items(
            project_id, "project.attention_history"
        ):
            payload = row_json(row)
            if str(payload.get("disposition", "open")) != "open":
                continue
            question = str(payload.get("question", ""))
            if not question.startswith("LITERATURE_GAP:"):
                continue
            appended_at = str(row["appended_at"])
            if p1_published_at is not None and appended_at <= p1_published_at:
                continue
            source_run_id = str(
                row["source_run_id"] or payload.get("source_run_id", "")
            )
            item_phase = payload.get("phase")
            if type(item_phase) is not str:
                item_phase = run_phases.get(source_run_id)
            if item_phase not in PHASE_IDS:
                continue
            item_method = _payload_method(payload) or run_methods.get(source_run_id)
            result.append(
                LiteratureGapSummary(
                    attention_id=str(
                        payload.get("attention_id", row["item_id"])
                    ),
                    reference=question[len("LITERATURE_GAP:"):].strip(),
                    raised_by_phase=item_phase,  # type: ignore[arg-type]
                    method_id=(
                        str(item_method.stable_id)
                        if item_method is not None
                        else None
                    ),
                )
            )
        return result

    def _latest_p1_publication_time(self, project_id: str) -> str | None:
        """Return the published_at timestamp of the latest P1 formal record."""
        latest: str | None = None
        for row in self.repository.list_current_records(project_id):
            if str(row["record_type"]) == "literature_synthesis":
                published = str(row["published_at"])
                if latest is None or published > latest:
                    latest = published
        return latest

    def _decision_brief(
        self,
        project_id: str,
        phase_id: str,
        method: MethodIdentity | None,
    ) -> DecisionBrief | None:
        candidates = [
            row
            for row in self.repository.list_current_records(project_id)
            if row["record_type"] == "phase_decision"
        ]
        selected: list[sqlite3.Row] = []
        for row in candidates:
            payload = row_json(row)
            if payload.get("phase") != phase_id:
                continue
            payload_method = _payload_method(payload)
            if method is not None and payload_method != method:
                continue
            if method is None and phase_id in {"P3", "P4", "P5"}:
                continue
            selected.append(row)
        row = max(selected, key=lambda item: item["published_at"], default=None)
        if row is None:
            return None
        payload = row_json(row)
        evidence_ids = [
            str(item) for item in payload.get("strongest_evidence_ids", [])
        ]
        evidence_links = [
            EvidenceLink(
                label=evidence_id,
                href=self._evidence_href(project_id, evidence_id),
            )
            for evidence_id in evidence_ids
        ]
        actions = []
        for item in payload.get("available_actions", []):
            if type(item) is not dict:
                continue
            label = str(item.get("label", "")).strip()
            consequence = str(item.get("consequence", "")).strip()
            if label and consequence:
                actions.append(
                    AvailableAction(label=label, consequence=consequence)
                )
        disagreement = payload.get("material_disagreement", "")
        if type(disagreement) is list:
            disagreement = "; ".join(str(item) for item in disagreement)
        return DecisionBrief(
            headline=str(payload.get("headline", "")),
            current_decision=str(
                payload.get("current_decision", payload.get("headline", ""))
            ),
            current_conclusion=str(payload.get("current_conclusion", "")),
            fundamental_contribution=str(
                payload.get("fundamental_contribution", "")
            ),
            what_changed=str(payload.get("what_changed", "")),
            strongest_evidence=evidence_links,
            principal_uncertainty=str(payload.get("principal_uncertainty", "")),
            principal_risk=str(payload.get("principal_risk", "")),
            material_disagreement=str(disagreement),
            rerun_question=str(payload.get("rerun_question", "")),
            available_actions=actions,
        )

    def _evidence(
        self,
        project_id: str,
        phase_id: str,
        method: MethodIdentity | None,
    ) -> list[EvidenceSummary]:
        if phase_id != "P4" or method is None:
            return []
        result: list[EvidenceSummary] = []
        for row in self.repository.list_collection_items(
            project_id, "p4.evidence_history"
        ):
            payload = row_json(row)
            if payload.get("phase") != phase_id or _payload_method(payload) != method:
                continue
            applicability = payload.get("applicability_at_creation")
            applicability = applicability if type(applicability) is dict else {}
            outcome = payload.get("scientific_outcome")
            outcome = outcome if type(outcome) is dict else {}
            eligibility = payload.get("evidence_eligibility")
            if type(eligibility) is dict:
                eligibility = eligibility.get("state")
            if eligibility not in {
                "included",
                "excluded",
                "unassessed",
                "not_applicable",
            }:
                eligibility = None
            evidence_id = str(payload.get("evidence_id", row["item_id"]))
            result.append(
                EvidenceSummary(
                    evidence_id=evidence_id,
                    label=str(
                        payload.get(
                            "label",
                            f"{str(payload.get('evidence_kind', 'Evidence')).title()}: "
                            f"{evidence_id}",
                        )
                    ),
                    assessment=str(
                        applicability.get(
                            "assessment", outcome.get("conclusion", "")
                        )
                    ),
                    eligibility=eligibility,
                    method_match=(
                        str(applicability["method_match"])
                        if type(applicability.get("method_match")) is str
                        else None
                    ),
                    href=self._evidence_href(project_id, evidence_id),
                )
            )
        return result

    def _evidence_href(self, project_id: str, evidence_id: str) -> str | None:
        for row in self.repository.list_collection_items(
            project_id, "p4.evidence_history"
        ):
            payload = row_json(row)
            if str(payload.get("evidence_id", row["item_id"])) != evidence_id:
                continue
            artifact_id = row["artifact_id"]
            if artifact_id is not None:
                return f"/api/v1/projects/{project_id}/artifacts/{artifact_id}"
        return None

    def _history_options(
        self,
        project_id: str,
        phase_id: str,
        method: MethodIdentity | None,
        document: dict[str, Any],
    ) -> list[dict[str, Any]]:
        policy = document.get("optional_context_policy", {})
        if type(policy) is not dict or policy.get("allows_selected_history") is not True:
            return []
        if phase_id in {"P3", "P4", "P5"} and method is None:
            return []
        record_type = {
            "P1": "literature_synthesis",
            "P2": "method_catalog",
            "P3": "theory_record",
            "P4": "empirical_synthesis",
            "P5": "manuscript",
        }[phase_id]
        current_ids = {
            str(row["generation_id"])
            for row in self.repository.list_current_records(project_id)
        }
        options: list[dict[str, Any]] = []
        for row in self.queries.list_formal_generations(
            project_id, record_type=record_type
        ):
            if str(row["generation_id"]) in current_ids:
                continue
            payload = row_json(row)
            if method is not None and _payload_method(payload) != method:
                continue
            options.append(
                {
                    "option_id": f"history.{row['generation_id']}",
                    "label": str(
                        payload.get(
                            "title",
                            f"Earlier {record_type.replace('_', ' ')}",
                        )
                    ),
                    "description": (
                        f"Formal generation published {row['published_at']}. "
                        "Include it only when it may answer the present rerun question."
                    ),
                    "artifact_pointer": {
                        "artifact_id": str(row["artifact_id"]),
                        "uri": f"artifact://sha256/{row['artifact_sha256']}",
                        "sha256": str(row["artifact_sha256"]),
                    },
                    "selected_by_default": False,
                    "required": False,
                }
            )
        return options[:20]

    def _record_status(
        self,
        payload: dict[str, Any],
        *,
        published_at: str,
        method_bound: bool,
        attention_items: Sequence[AttentionSummary],
    ) -> ScientificStatus:
        alignment = payload.get("alignment")
        if type(alignment) is not dict:
            alignment = payload.get("alignment_at_creation")
        alignment_value = (
            str(alignment.get("state"))
            if type(alignment) is dict
            else ("exact" if method_bound else "not_applicable")
        )
        if alignment_value not in {
            "exact",
            "compatible",
            "unassessed",
            "outdated",
            "not_applicable",
        }:
            alignment_value = "unassessed" if method_bound else "not_applicable"
        attention = _attention_level(attention_items)
        return ScientificStatus(
            publication_state="formal",
            record_position="current",
            alignment=alignment_value,
            attention=attention,
            attention_count=len(attention_items),
            scientific_outcome=_outcome(payload),
            last_published_at=published_at,
        )

    def _projection(self, project_id: str) -> ProjectionStamp:
        row = self.repository.get_project(project_id)
        return ProjectionStamp(
            authority_event_root_sha256=str(row["authority_root_sha256"]),
            projected_at=str(row["updated_at"]),
            view_revision=int(row["current_revision"]),
        )

    def _selected_method_row(
        self, project_id: str, method_id: str | None
    ) -> MethodRow | None:
        if method_id is None:
            return None
        return next(
            (
                item
                for item in self.list_methods(project_id)
                if item.identity.stable_id == method_id
            ),
            None,
        )

    def _selected_method(
        self, project_id: str, method_id: str | None
    ) -> MethodIdentity | None:
        row = self._selected_method_row(project_id, method_id)
        return (
            MethodIdentity.from_dict(row.identity.model_dump())
            if row is not None
            else None
        )

    def _current_input_options(
        self,
        project_id: str,
        document: dict[str, Any],
        mode: str,
        method: MethodIdentity | None,
        phase_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        applicable = tuple(
            item
            for item in document["required_inputs"]
            # Mode-scoped inputs apply only in their declared modes.  The
            # contract schema allows the required_in_modes key only with
            # presence "required_in_modes", so one condition suffices.
            if not (
                str(item["presence"]) == "required_in_modes"
                and mode not in item.get("required_in_modes", [])
            )
        )
        # Phase/mode-specific visibility: mark record types that aren't
        # useful as researcher-facing context cards. They stay in the
        # options (auto-selected) but get hidden=True so the frontend
        # doesn't render a card for them.
        hidden_record_types = _hidden_context_record_types(phase_id, mode)
        references: dict[str, Any] = {}
        for item in applicable:
            match = str(item["method_match"])
            query_method = method if match in {"exact", "same_stable_method"} else None
            references[str(item["input_id"])] = self.queries.current_record(
                project_id=project_id,
                record_type=str(item["record_type"]),
                method_identity=query_method,
                match_policy=match,
            )
        rerun_active = any(
            str(item["presence"]) == "required_on_rerun"
            and references[str(item["input_id"])] is not None
            for item in applicable
        )

        options: list[dict[str, Any]] = []
        findings: list[dict[str, str]] = []
        for item in applicable:
            presence = str(item["presence"])
            # Mirror the execution layer (harness.inputs.resolve_run_inputs):
            # presence "always" and mode-applicable "required_in_modes" inputs
            # are mandatory; the UI must lock them checked or the harness
            # rejects the run.
            required = presence in {"always", "required_in_modes"} or (
                presence == "required_on_rerun" and rerun_active
            )
            reference = references[str(item["input_id"])]
            if reference is None:
                if required:
                    findings.append(
                        {
                            "code": "input.required_current_record_missing",
                            "message": f"Required current {item['record_type']} is unavailable.",
                        }
                    )
                    continue
                # Optional record that doesn't exist yet — surface as a
                # disabled, unchecked card so the user sees the phase
                # slot but cannot select it.
                options.append(
                    {
                        "option_id": str(item["input_id"]),
                        "label": str(item["record_type"]).replace("_", " ").title(),
                        "description": str(item["purpose"]),
                        "feedback": None,
                        "highlight_artifact_id": None,
                        "size_bytes": None,
                        "group": _context_group(str(item["record_type"])),
                        "hidden": str(item["record_type"]) in hidden_record_types,
                        "artifact_pointer": None,
                        "generation_id": None,
                        "selected_by_default": False,
                        "required": False,
                        "disabled": True,
                        "disabled_reason": "No current record for this method.",
                    }
                )
                continue
            options.append(
                {
                    "option_id": str(item["input_id"]),
                    "label": str(item["record_type"]).replace("_", " ").title(),
                    "description": str(item["purpose"]),
                    "feedback": reference.summary,
                    "highlight_artifact_id": reference.highlight_artifact_id,
                    "size_bytes": reference.size_bytes,
                    "group": _context_group(str(item["record_type"])),
                    "hidden": str(item["record_type"]) in hidden_record_types,
                    "artifact_pointer": {
                        "artifact_id": str(reference.artifact.artifact_id),
                        "uri": reference.artifact.uri,
                        "sha256": str(reference.artifact.sha256),
                    },
                    "generation_id": str(reference.generation_id),
                    "selected_by_default": True,
                    "required": required,
                }
            )
        return options, findings
    def _phase_current_record(
        self,
        project_id: str,
        phase_id: str,
        method: MethodIdentity | None,
    ) -> sqlite3.Row | None:
        record_type = {
            "P1": "literature_synthesis",
            "P2": "method_catalog",
            "P3": "theory_record",
            "P4": "empirical_synthesis",
            "P5": "manuscript",
        }[phase_id]
        candidates = [
            row
            for row in self.repository.list_current_records(project_id)
            if row["record_type"] == record_type
        ]
        if method is not None:
            candidates = [
                row
                for row in candidates
                if _payload_method(row_json(row)) == method
            ]
        return max(candidates, key=lambda row: row["published_at"], default=None)

    def _method_phase_statuses(
        self, project_id: str, method: MethodIdentity
    ) -> dict[str, ScientificStatus]:
        statuses: dict[str, ScientificStatus] = {}
        for phase_id in ("P3", "P4", "P5"):
            row = self._phase_current_record(project_id, phase_id, method)
            statuses[phase_id] = (
                self._record_status(
                    row_json(row),
                    published_at=str(row["published_at"]),
                    method_bound=True,
                    attention_items=self._attention_items(
                        project_id, phase_id=phase_id, method=method
                    ),
                )
                if row is not None
                else ScientificStatus(
                    record_position="none",
                    alignment="unassessed",
                    attention=_attention_level(
                        self._attention_items(
                            project_id, phase_id=phase_id, method=method
                        )
                    ),
                    attention_count=len(
                        self._attention_items(
                            project_id, phase_id=phase_id, method=method
                        )
                    ),
                    scientific_outcome="not_assessed",
                )
            )
        return statuses


_PHASE_RECORD_TYPES = {
    "P1": {
        "literature_library",
        "literature_synthesis",
        "literature_coverage",
    },
    "P2": {"method_catalog", "method_record"},
    "P3": {"theory_record"},
    "P4": {
        "empirical_evidence_index",
        "empirical_synthesis",
        "implementation_record",
    },
    "P5": {"manuscript", "review_issue_ledger"},
}


def _phase_rows(
    rows: Sequence[sqlite3.Row],
    phase_id: str,
    method: MethodIdentity | None,
) -> list[sqlite3.Row]:
    decision_slot = f"{phase_id.lower()}.phase_decision.current"
    selected = [
        row
        for row in rows
        if row["record_type"] in _PHASE_RECORD_TYPES[phase_id]
        or (
            row["record_type"] == "phase_decision"
            and str(row["slot_key"]).endswith(decision_slot)
        )
    ]
    if method is None or phase_id not in {"P3", "P4", "P5"}:
        return selected
    return [
        row
        for row in selected
        if _payload_method(row_json(row)) == method
    ]


def _attention_level(items: Sequence[AttentionSummary]) -> str:
    priority = {
        "informational": 0,
        "monitor": 1,
        "reassessment_required": 2,
        "blocking": 3,
    }
    if not items:
        return "none"
    highest = max(items, key=lambda item: priority[item.severity]).severity
    return "none" if highest == "informational" else highest


def _aggregate_status(statuses: Sequence[ScientificStatus]) -> ScientificStatus:
    if not statuses:
        return ScientificStatus(
            record_position="none",
            alignment="unassessed",
            attention="none",
            attention_count=0,
            scientific_outcome="not_assessed",
        )
    alignment_priority = {
        "not_applicable": 0,
        "exact": 1,
        "compatible": 2,
        "unassessed": 3,
        "outdated": 4,
    }
    attention_priority = {
        "none": 0,
        "monitor": 1,
        "reassessment_required": 2,
        "blocking": 3,
    }
    alignments = [item.alignment for item in statuses if item.alignment is not None]
    attentions = [item.attention for item in statuses if item.attention is not None]
    outcomes = {
        item.scientific_outcome
        for item in statuses
        if item.scientific_outcome is not None
    }
    return ScientificStatus(
        publication_state="formal",
        record_position="current",
        alignment=(
            max(alignments, key=lambda item: alignment_priority[item])
            if alignments
            else None
        ),
        attention=(
            max(attentions, key=lambda item: attention_priority[item])
            if attentions
            else None
        ),
        attention_count=sum(item.attention_count or 0 for item in statuses),
        scientific_outcome=next(iter(outcomes)) if len(outcomes) == 1 else None,
        last_published_at=max(
            (
                item.last_published_at
                for item in statuses
                if item.last_published_at is not None
            ),
            default=None,
        ),
    )


def _mathematical_summary(value: Any) -> str:
    if type(value) is not dict:
        return str(value)
    explicit = value.get("summary") or value.get("mathematical_summary")
    if type(explicit) is str and explicit.strip():
        return explicit.strip()
    canonical = value.get("canonical_definition")
    if type(canonical) is dict:
        statements: list[str] = []
        target = canonical.get("target_or_estimand")
        if type(target) is dict and type(target.get("definition")) is str:
            statements.append(f"Target: {target['definition']}")
        equation = canonical.get("objective_or_estimating_equation")
        if type(equation) is dict and type(equation.get("definition")) is str:
            statements.append(f"Estimating equation: {equation['definition']}")
        if statements:
            return " ".join(statements)
    locator = value.get("definition_locator")
    return str(locator) if locator is not None else ""


def _payload_method(payload: dict[str, Any]) -> MethodIdentity | None:
    value = payload.get("method_identity") or payload.get("identity")
    return MethodIdentity.from_dict(value) if type(value) is dict else None


def _record_summary(payload: dict[str, Any]) -> str:
    for key in ("summary", "current_conclusion", "synthesis", "abstract"):
        value = payload.get(key)
        if type(value) is str:
            return value
    return "A formal structured record is available."


def _outcome(payload: dict[str, Any]) -> str:
    value = payload.get("scientific_outcome")
    if type(value) is dict:
        value = value.get("state")
    if type(value) is str and value in {
        "supported",
        "partially_supported",
        "contradicted",
        "inconclusive",
        "not_assessed",
        "not_applicable",
    }:
        return str(value)
    return "not_assessed"


def _provenance_summary(payload: dict[str, Any]) -> str | None:
    value = payload.get("literature_provenance")
    if type(value) is list and value:
        return f"Linked to {len(value)} literature provenance record(s)."
    return None


def _method_evaluation(payload: Mapping[str, Any]) -> MethodEvaluation | None:
    """Assemble the sealed three-axis evaluation; never fabricate scores.

    Returns None unless the record carries a well-formed evaluation block;
    absent or malformed blocks surface as "not yet evaluated".
    """
    evaluation = payload.get("evaluation")
    if not isinstance(evaluation, Mapping):
        return None
    for axis in (
        "theoretical_validity",
        "literature_positioning",
        "empirical_feasibility",
    ):
        entry = evaluation.get(axis)
        if not isinstance(entry, Mapping):
            return None
        score = entry.get("score")
        justification = entry.get("justification")
        if type(score) is not int or not 1 <= score <= 10:
            return None
        if not isinstance(justification, str) or not justification.strip():
            return None
        refs = entry.get("issue_refs")
        if not isinstance(refs, list) or any(not isinstance(r, str) for r in refs):
            return None
    if not isinstance(evaluation.get("adjudicated_at"), str):
        return None
    basis = evaluation.get("review_basis_ids")
    if not isinstance(basis, list) or not basis:
        return None
    try:
        return MethodEvaluation.model_validate(evaluation)
    except ValidationError:
        return None


def _action_id(*parts: str) -> str:
    return "action." + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


_CONTEXT_GROUPS: dict[str, str] = {
    "project_brief": "brief",
    "literature_synthesis": "literature",
    "literature_library": "literature",
    "literature_coverage": "literature",
    "method_catalog": "catalog",
    "method_record": "catalog",
    "theory_record": "theory",
    "empirical_evidence_index": "empirical",
    "empirical_synthesis": "empirical",
    "implementation_record": "empirical",
    "manuscript": "manuscript",
    "review_issue_ledger": "manuscript",
    "phase_decision": "decision",
}


def _context_group(record_type: str) -> str:
    """Map a record_type to a researcher-facing context group."""
    return _CONTEXT_GROUPS.get(record_type, "other")


# Record types hidden from the researcher-facing context UI for each phase.
# The contracts still list them as required inputs for the execution layer,
# but they don't add value as visible context cards for the researcher.
_HIDDEN_BY_PHASE: dict[str, frozenset[str]] = {
    "P2": frozenset({"literature_library"}),
    "P3": frozenset({"literature_library"}),
    "P4": frozenset({"literature_library"}),
    "P5": frozenset({"literature_library"}),
}

# Record types hidden for specific (phase, mode) combinations.
# P2's optional method-scoped context (theory/empirical/manuscript) only
# resolves when a method is selected (focused_method mode); in full_catalog
# mode the records never match, so the empty slots are hidden entirely
# instead of shown as unavailable cards.
_HIDDEN_BY_MODE: dict[tuple[str, str], frozenset[str]] = {
    ("P2", "p2.full_catalog"): frozenset(
        {"theory_record", "empirical_synthesis", "manuscript"}
    ),
}


def _hidden_context_record_types(phase_id: str, mode: str) -> frozenset[str]:
    """Return record types to hide from the context UI for this phase+mode."""
    phase_hidden = _HIDDEN_BY_PHASE.get(phase_id, frozenset())
    mode_hidden = _HIDDEN_BY_MODE.get((phase_id, mode), frozenset())
    return phase_hidden | mode_hidden


__all__ = [
    "ACTIVE_RUN_STATES",
    "ResearchProjectionService",
    "project_summary",
]
