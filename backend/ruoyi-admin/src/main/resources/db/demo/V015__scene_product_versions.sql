-- Clean cutover to immutable product versions. This DISCARDS all previous product business records
-- (scenes, drafts, files, collections, ZIP cache, deletion receipts, audit). Accounts, menus and
-- Flyway history (sys_* tables) are untouched. Never apply to a daily database without explicit approval.
-- ar_audit row-level UPDATE/DELETE triggers do not fire for TRUNCATE, so audit is cleared with the rest.
TRUNCATE ar_audit, ar_file_deletion, ar_zip_export, ar_draft_file, ar_draft_collection, ar_draft, ar_scene RESTART IDENTITY;

DROP TRIGGER ar_scene_published_draft_guard ON ar_scene;
DROP FUNCTION ar_scene_published_draft_guard();
ALTER TABLE ar_scene DROP CONSTRAINT ar_scene_published_ck;
-- Dropping the column also drops its foreign key and unique index.
ALTER TABLE ar_scene DROP COLUMN published_draft_id;
DROP TABLE ar_zip_export, ar_file_deletion, ar_draft_file, ar_draft_collection, ar_draft;

CREATE TABLE ar_scene_version (
    id uuid PRIMARY KEY,
    scene_id uuid NOT NULL REFERENCES ar_scene(id),
    version_no integer NOT NULL CHECK(version_no > 0),
    request_key uuid NOT NULL,
    description varchar(2000) NOT NULL DEFAULT '',
    descriptor jsonb NOT NULL,
    lock_version bigint NOT NULL DEFAULT 0 CHECK(lock_version >= 0),
    creator_id bigint NOT NULL REFERENCES sys_user(user_id),
    creator_name varchar(30) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(scene_id, version_no),
    UNIQUE(scene_id, request_key),
    UNIQUE(id, scene_id)
);

CREATE TABLE ar_version_file (
    id uuid PRIMARY KEY,
    version_id uuid NOT NULL REFERENCES ar_scene_version(id),
    relative_path varchar(1024) NOT NULL CHECK(char_length(relative_path) BETWEEN 1 AND 1024
        AND position('/' in relative_path) <> 1 AND relative_path !~ '[\\]'),
    expected_bytes bigint NOT NULL CHECK(expected_bytes > 0),
    expected_sha256 varchar(64) NOT NULL CHECK(expected_sha256 ~ '^[0-9a-f]{64}$'),
    storage_key varchar(40) NOT NULL UNIQUE CHECK(storage_key = id::text || '.bin'),
    status varchar(20) NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','UPLOADING','AVAILABLE','FAILED')),
    verified_bytes bigint,
    verified_sha256 varchar(64),
    failure_reason varchar(500),
    attempts integer NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    creator_id bigint NOT NULL REFERENCES sys_user(user_id),
    creator_name varchar(30) NOT NULL,
    last_actor_id bigint NOT NULL REFERENCES sys_user(user_id),
    last_actor_name varchar(30) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(version_id, relative_path),
    CHECK((status = 'AVAILABLE' AND verified_bytes IS NOT NULL AND verified_bytes = expected_bytes
        AND verified_sha256 IS NOT NULL AND verified_sha256 = expected_sha256 AND failure_reason IS NULL)
        OR (status <> 'AVAILABLE' AND verified_bytes IS NULL AND verified_sha256 IS NULL)),
    CHECK(status <> 'FAILED' OR failure_reason IS NOT NULL)
);
CREATE INDEX ar_version_file_status_idx ON ar_version_file(status) WHERE status <> 'AVAILABLE';

-- Whole-version deletion intent, failure and minimal idempotency receipt. No FK to the version so the
-- receipt outlives the deleted row; it holds no file content or descriptor.
CREATE TABLE ar_version_deletion (
    version_id uuid PRIMARY KEY,
    scene_id uuid NOT NULL REFERENCES ar_scene(id),
    request_key uuid NOT NULL,
    actor_id bigint NOT NULL REFERENCES sys_user(user_id),
    actor_name varchar(30) NOT NULL,
    requested_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    failure_reason varchar(500),
    UNIQUE(scene_id, request_key),
    CHECK(completed_at IS NULL OR failure_reason IS NULL)
);
CREATE INDEX ar_version_deletion_pending_idx ON ar_version_deletion(version_id) WHERE completed_at IS NULL;

-- Single current publication pointer. The composite FK keeps it inside its own scene.
ALTER TABLE ar_scene ADD COLUMN published_version_id uuid;
ALTER TABLE ar_scene ADD CONSTRAINT ar_scene_published_version_fk
    FOREIGN KEY (published_version_id, id) REFERENCES ar_scene_version(id, scene_id);
ALTER TABLE ar_scene ADD CONSTRAINT ar_scene_published_ck CHECK (
    (published_version_id IS NULL AND published_at IS NULL AND published_by_id IS NULL AND published_by_name IS NULL)
    OR (published_version_id IS NOT NULL AND published_at IS NOT NULL AND published_by_id IS NOT NULL AND published_by_name IS NOT NULL)
);
CREATE UNIQUE INDEX ar_scene_published_version_uidx ON ar_scene(published_version_id) WHERE published_version_id IS NOT NULL;
