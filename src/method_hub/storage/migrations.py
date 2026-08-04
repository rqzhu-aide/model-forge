"""Versioned SQLite schema for the greenfield Method Hub repository."""

from __future__ import annotations

from .database import Migration


ZERO_SHA256 = "0" * 64


def _immutable_triggers(table: str) -> tuple[str, str]:
    return (
        f"""
        CREATE TRIGGER {table}_immutable_update
        BEFORE UPDATE ON {table}
        BEGIN
            SELECT RAISE(ABORT, '{table} rows are immutable');
        END
        """,
        f"""
        CREATE TRIGGER {table}_immutable_delete
        BEFORE DELETE ON {table}
        BEGIN
            SELECT RAISE(ABORT, '{table} rows are immutable');
        END
        """,
    )


_CONTROL_SCHEMA = (
    f"""
    CREATE TABLE projects (
        project_id TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
        authority_sequence INTEGER NOT NULL DEFAULT 0
            CHECK (authority_sequence >= 0),
        authority_root_sha256 TEXT NOT NULL DEFAULT '{ZERO_SHA256}'
            CHECK (length(authority_root_sha256) = 64),
        current_revision INTEGER NOT NULL DEFAULT 0
            CHECK (current_revision >= 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE raw_command_requests (
        request_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
        raw_sha256 TEXT NOT NULL CHECK (length(raw_sha256) = 64),
        payload_json TEXT NOT NULL,
        received_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX raw_command_requests_project_time
        ON raw_command_requests(project_id, received_at)
    """,
    """
    CREATE TABLE sealed_commands (
        command_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
        raw_request_id TEXT NOT NULL
            REFERENCES raw_command_requests(request_id) ON DELETE RESTRICT,
        idempotency_key TEXT NOT NULL,
        command_sha256 TEXT NOT NULL CHECK (length(command_sha256) = 64),
        payload_json TEXT NOT NULL,
        sealed_at TEXT NOT NULL,
        UNIQUE (project_id, idempotency_key)
    )
    """,
    """
    CREATE INDEX sealed_commands_project_time
        ON sealed_commands(project_id, sealed_at)
    """,
    """
    CREATE TABLE runs (
        run_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
        command_id TEXT NOT NULL UNIQUE
            REFERENCES sealed_commands(command_id) ON DELETE RESTRICT,
        status TEXT NOT NULL,
        head_sequence INTEGER NOT NULL CHECK (head_sequence >= 1),
        cancellation_fenced INTEGER NOT NULL DEFAULT 0
            CHECK (cancellation_fenced IN (0, 1)),
        new_role_fenced INTEGER NOT NULL DEFAULT 0
            CHECK (new_role_fenced IN (0, 1)),
        cancellation_command_id TEXT
            REFERENCES sealed_commands(command_id) ON DELETE RESTRICT,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX runs_project_status_time
        ON runs(project_id, status, updated_at)
    """,
    """
    CREATE TABLE run_events (
        event_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
        sequence INTEGER NOT NULL CHECK (sequence >= 1),
        status TEXT NOT NULL,
        event_sha256 TEXT NOT NULL CHECK (length(event_sha256) = 64),
        payload_json TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE (run_id, sequence)
    )
    """,
    """
    CREATE TRIGGER run_events_monotone_insert
    BEFORE INSERT ON run_events
    WHEN NEW.sequence != COALESCE(
        (SELECT MAX(sequence) + 1 FROM run_events WHERE run_id = NEW.run_id),
        1
    )
    BEGIN
        SELECT RAISE(ABORT, 'run event sequence must be monotone');
    END
    """,
    """
    CREATE TABLE run_manifests (
        run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE RESTRICT,
        manifest_sha256 TEXT NOT NULL CHECK (length(manifest_sha256) = 64),
        payload_json TEXT NOT NULL,
        sealed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE artifacts (
        artifact_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
        sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
        size INTEGER NOT NULL CHECK (size >= 0),
        media_type TEXT NOT NULL,
        storage_uri TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        recorded_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX artifacts_project_digest
        ON artifacts(project_id, sha256)
    """,
) + sum(
    (
        _immutable_triggers("raw_command_requests"),
        _immutable_triggers("sealed_commands"),
        _immutable_triggers("run_events"),
        _immutable_triggers("run_manifests"),
        _immutable_triggers("artifacts"),
    ),
    (),
)


_EXECUTION_SCHEMA = (
    """
    CREATE TABLE role_execution_intents (
        execution_id TEXT PRIMARY KEY,
        invocation_id TEXT NOT NULL UNIQUE,
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
        invocation_sha256 TEXT NOT NULL CHECK (length(invocation_sha256) = 64),
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX role_execution_intents_run
        ON role_execution_intents(run_id, created_at)
    """,
    """
    CREATE TABLE role_execution_acknowledgements (
        execution_id TEXT PRIMARY KEY
            REFERENCES role_execution_intents(execution_id) ON DELETE RESTRICT,
        external_execution_id TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        acknowledged_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE role_execution_heartbeats (
        heartbeat_id TEXT PRIMARY KEY,
        execution_id TEXT NOT NULL
            REFERENCES role_execution_intents(execution_id) ON DELETE RESTRICT,
        sequence INTEGER NOT NULL CHECK (sequence >= 1),
        payload_json TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE (execution_id, sequence)
    )
    """,
    """
    CREATE TRIGGER role_execution_heartbeats_monotone_insert
    BEFORE INSERT ON role_execution_heartbeats
    WHEN NEW.sequence != COALESCE(
        (
            SELECT MAX(sequence) + 1
            FROM role_execution_heartbeats
            WHERE execution_id = NEW.execution_id
        ),
        1
    )
    BEGIN
        SELECT RAISE(ABORT, 'execution heartbeat sequence must be monotone');
    END
    """,
    """
    CREATE TABLE role_execution_closures (
        closure_id TEXT PRIMARY KEY,
        execution_id TEXT NOT NULL UNIQUE
            REFERENCES role_execution_intents(execution_id) ON DELETE RESTRICT,
        closure_sha256 TEXT NOT NULL CHECK (length(closure_sha256) = 64),
        payload_json TEXT NOT NULL,
        closed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE run_submissions (
        submission_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id) ON DELETE RESTRICT,
        submission_sha256 TEXT NOT NULL CHECK (length(submission_sha256) = 64),
        payload_json TEXT NOT NULL,
        submitted_at TEXT NOT NULL
    )
    """,
) + sum(
    (
        _immutable_triggers("role_execution_intents"),
        _immutable_triggers("role_execution_acknowledgements"),
        _immutable_triggers("role_execution_heartbeats"),
        _immutable_triggers("role_execution_closures"),
        _immutable_triggers("run_submissions"),
    ),
    (),
)


_PUBLICATION_SCHEMA = (
    """
    CREATE TABLE publication_receipts (
        receipt_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
        run_id TEXT REFERENCES runs(run_id) ON DELETE RESTRICT,
        command_id TEXT REFERENCES sealed_commands(command_id) ON DELETE RESTRICT,
        prior_authority_sequence INTEGER NOT NULL CHECK (prior_authority_sequence >= 0),
        new_authority_sequence INTEGER NOT NULL CHECK (
            new_authority_sequence >= prior_authority_sequence
        ),
        prior_authority_root_sha256 TEXT NOT NULL
            CHECK (length(prior_authority_root_sha256) = 64),
        new_authority_root_sha256 TEXT NOT NULL
            CHECK (length(new_authority_root_sha256) = 64),
        prior_current_revision INTEGER NOT NULL CHECK (prior_current_revision >= 0),
        new_current_revision INTEGER NOT NULL CHECK (
            new_current_revision >= prior_current_revision
        ),
        receipt_sha256 TEXT NOT NULL CHECK (length(receipt_sha256) = 64),
        payload_json TEXT NOT NULL,
        committed_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX publication_receipts_project_time
        ON publication_receipts(project_id, committed_at)
    """,
    """
    CREATE TABLE formal_generations (
        generation_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
        record_type TEXT NOT NULL,
        logical_slot TEXT,
        artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id) ON DELETE RESTRICT,
        source_run_id TEXT REFERENCES runs(run_id) ON DELETE RESTRICT,
        supersedes_generation_id TEXT
            REFERENCES formal_generations(generation_id) ON DELETE RESTRICT,
        content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
        payload_json TEXT NOT NULL,
        published_at TEXT NOT NULL,
        UNIQUE (project_id, generation_id)
    )
    """,
    """
    CREATE INDEX formal_generations_project_type_time
        ON formal_generations(project_id, record_type, published_at)
    """,
    """
    CREATE TABLE current_slots (
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
        slot_key TEXT NOT NULL,
        generation_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision >= 1),
        updated_at TEXT NOT NULL,
        PRIMARY KEY (project_id, slot_key),
        FOREIGN KEY (project_id, generation_id)
            REFERENCES formal_generations(project_id, generation_id)
            ON DELETE RESTRICT
    )
    """,
    """
    CREATE INDEX current_slots_generation
        ON current_slots(generation_id)
    """,
    """
    CREATE TABLE cumulative_collection_items (
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
        collection_key TEXT NOT NULL,
        item_id TEXT NOT NULL,
        object_type TEXT NOT NULL,
        artifact_id TEXT REFERENCES artifacts(artifact_id) ON DELETE RESTRICT,
        source_run_id TEXT REFERENCES runs(run_id) ON DELETE RESTRICT,
        content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
        payload_json TEXT NOT NULL,
        appended_at TEXT NOT NULL,
        PRIMARY KEY (project_id, collection_key, item_id)
    )
    """,
    """
    CREATE INDEX cumulative_collection_items_project_type
        ON cumulative_collection_items(project_id, object_type, appended_at)
    """,
    """
    CREATE TABLE authority_events (
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
        sequence INTEGER NOT NULL CHECK (sequence >= 1),
        event_id TEXT NOT NULL UNIQUE,
        event_type TEXT NOT NULL,
        prior_root_sha256 TEXT NOT NULL CHECK (length(prior_root_sha256) = 64),
        content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
        root_sha256 TEXT NOT NULL CHECK (length(root_sha256) = 64),
        receipt_id TEXT NOT NULL REFERENCES publication_receipts(receipt_id)
            ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
        payload_json TEXT NOT NULL,
        committed_at TEXT NOT NULL,
        PRIMARY KEY (project_id, sequence)
    )
    """,
    f"""
    CREATE TRIGGER authority_events_monotone_insert
    BEFORE INSERT ON authority_events
    WHEN NEW.sequence != COALESCE(
        (
            SELECT MAX(sequence) + 1
            FROM authority_events
            WHERE project_id = NEW.project_id
        ),
        1
    ) OR NEW.prior_root_sha256 != COALESCE(
        (
            SELECT root_sha256
            FROM authority_events
            WHERE project_id = NEW.project_id
            ORDER BY sequence DESC
            LIMIT 1
        ),
        '{ZERO_SHA256}'
    )
    BEGIN
        SELECT RAISE(ABORT, 'authority event chain is not monotone');
    END
    """,
    """
    CREATE TABLE profile_mappings (
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
        role_key TEXT NOT NULL,
        profile_name TEXT NOT NULL,
        settings_json TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision >= 1),
        updated_at TEXT NOT NULL,
        PRIMARY KEY (project_id, role_key)
    )
    """,
    """
    CREATE TABLE project_settings (
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
        setting_key TEXT NOT NULL,
        value_json TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision >= 1),
        updated_at TEXT NOT NULL,
        PRIMARY KEY (project_id, setting_key)
    )
    """,
) + sum(
    (
        _immutable_triggers("publication_receipts"),
        _immutable_triggers("formal_generations"),
        _immutable_triggers("cumulative_collection_items"),
        _immutable_triggers("authority_events"),
    ),
    (),
)


_DIAGNOSTIC_SCHEMA = (
    """
    CREATE TABLE diagnostic_invocations (
        invocation_id TEXT PRIMARY KEY,
        idempotency_key TEXT NOT NULL DEFAULT '',
        project_id TEXT NOT NULL,
        role TEXT NOT NULL,
        profile_name TEXT NOT NULL,
        external_execution_id TEXT,
        process_identity_json TEXT,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'preflight', 'creating',
                              'launch_acknowledged', 'running', 'closing',
                              'cancel_requested', 'timeout_requested',
                              'terminating', 'succeeded', 'failed',
                              'cancelled', 'timed_out', 'unresolved')),
        exit_code INTEGER,
        summary TEXT NOT NULL DEFAULT '',
        diagnostic_text TEXT NOT NULL DEFAULT '',
        memory_state_before TEXT,
        memory_state_after TEXT,
        memory_policy TEXT NOT NULL DEFAULT 'persistent',
        manifest_sha256 TEXT,
        payload_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (idempotency_key)
    )
    """,
    """
    CREATE INDEX diagnostic_invocations_project
        ON diagnostic_invocations(project_id, created_at)
    """,
    """
    CREATE INDEX diagnostic_invocations_status
        ON diagnostic_invocations(status, updated_at)
    """,
    """
    CREATE TABLE diagnostic_fencing_tokens (
        invocation_id TEXT PRIMARY KEY
            REFERENCES diagnostic_invocations(invocation_id) ON DELETE CASCADE,
        token INTEGER NOT NULL,
        holder TEXT,
        lease_expires_at TEXT,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE profile_execution_locks (
        profile_name TEXT PRIMARY KEY,
        invocation_id TEXT NOT NULL
            REFERENCES diagnostic_invocations(invocation_id) ON DELETE CASCADE,
        token INTEGER NOT NULL,
        acquired_at TEXT NOT NULL,
        lease_expires_at TEXT NOT NULL
    )
    """,
)


_RUN_SEAL_SCHEMA = (
    """
    CREATE TABLE run_profile_seals (
        seal_id TEXT PRIMARY KEY,
        invocation_id TEXT NOT NULL UNIQUE,
        project_id TEXT NOT NULL,
        role TEXT NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE,
        run_dir TEXT NOT NULL,
        manifest_sha256 TEXT NOT NULL CHECK (length(manifest_sha256) = 64),
        sealed_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX run_profile_seals_project_role
        ON run_profile_seals(project_id, role, sealed_at)
    """,
    """
    CREATE TABLE project_role_state_locks (
        profile_name TEXT PRIMARY KEY,
        invocation_id TEXT NOT NULL,
        token INTEGER NOT NULL,
        acquired_at TEXT NOT NULL,
        lease_expires_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE run_fencing_tokens (
        invocation_id TEXT PRIMARY KEY,
        token INTEGER NOT NULL,
        holder TEXT,
        lease_expires_at TEXT,
        updated_at TEXT NOT NULL
    )
    """,
) + _immutable_triggers("run_profile_seals")


#: One post-execution output validation report per launch (WP-E1).  The
#: verdict is recorded after quiescence; the full report JSON preserves
#: the raw-output inventory and per-check evidence.  This is a sibling
#: table — the immutable seal registry is never touched by validation.
_VALIDATION_REPORT_SCHEMA = (
    """
    CREATE TABLE run_validation_reports (
        launch_id TEXT PRIMARY KEY
            REFERENCES run_launch_records(launch_id) ON DELETE RESTRICT,
        invocation_id TEXT NOT NULL,
        seal_id TEXT NOT NULL REFERENCES run_profile_seals(seal_id)
            ON DELETE RESTRICT,
        verdict TEXT NOT NULL CHECK (verdict IN ('pass', 'fail')),
        report_json TEXT NOT NULL,
        validated_at TEXT NOT NULL
    )
    """,
)


#: One supervised launch attempt per row (WP-E0).  Unlike the seal
#: registry, launch records are intentionally mutable: a row is inserted
#: with ``status = 'running'`` when the launch intent is recorded and
#: updated once to a terminal status when the process closes.
_LAUNCH_RECORD_SCHEMA = (
    """
    CREATE TABLE run_launch_records (
        launch_id TEXT PRIMARY KEY,
        seal_id TEXT NOT NULL REFERENCES run_profile_seals(seal_id) ON DELETE RESTRICT,
        invocation_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('running', 'succeeded',
                                              'failed', 'cancelled')),
        external_execution_id TEXT,
        exit_code INTEGER,
        task_brief_sha256 TEXT
            CHECK (task_brief_sha256 IS NULL OR length(task_brief_sha256) = 64),
        launched_at TEXT NOT NULL,
        closed_at TEXT
    )
    """,
    """
    CREATE INDEX run_launch_records_invocation_time
        ON run_launch_records(invocation_id, launched_at)
    """,
)


HUB_MIGRATIONS = (
    Migration(1, _CONTROL_SCHEMA, name="control and run storage"),
    Migration(2, _EXECUTION_SCHEMA, name="role execution and submission storage"),
    Migration(3, _PUBLICATION_SCHEMA, name="formal publication and settings storage"),
    Migration(4, _DIAGNOSTIC_SCHEMA, name="diagnostic invocations, fencing, profile mutex"),
    Migration(
        5,
        ("ALTER TABLE diagnostic_invocations ADD COLUMN evidence_json TEXT",),
        name="Slice 7: evidence package (image digest, brief sha, config digest)",
    ),
    Migration(
        6,
        _RUN_SEAL_SCHEMA,
        name="run profile seals, project-role state locks, run fencing tokens",
    ),
    Migration(
        7,
        _LAUNCH_RECORD_SCHEMA,
        name="supervised launch records for sealed-run execution (WP-E0)",
    ),
    Migration(
        8,
        _VALIDATION_REPORT_SCHEMA,
        name="post-execution output validation reports (WP-E1)",
    ),
)


__all__ = ["HUB_MIGRATIONS", "ZERO_SHA256"]
