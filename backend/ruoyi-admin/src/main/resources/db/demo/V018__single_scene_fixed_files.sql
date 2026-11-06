-- One scene owns one fixed file list. A historical content version becomes one scene:
--   * the published version (if any) keeps the original scene id, name, enabled state and visibility;
--     its description and files move to that scene. Without a published version the latest version
--     keeps the original scene id but the scene is disabled.
--   * every other version becomes its own disabled scene with the version UUID as scene id and a
--     distinguishable name, keeping the version's file rows, file UUIDs and storage keys unchanged.
-- Payload bytes are never copied or deleted here; only rows move/rename. Audit stays untouched and
-- old VERSION_* audit labels remain immutable history.
--
-- Deterministic mapping evidence:
--   ar_v018_version_map(version_id, scene_id) lists every migrated version; scene_id = original scene
--   for the published (or latest when nothing was published) version, otherwise scene_id = version_id.

ALTER TABLE ar_scene ADD COLUMN description varchar(2000) NOT NULL DEFAULT '';
ALTER TABLE ar_scene ADD COLUMN request_key uuid;

-- A completed whole-version deletion receipt is historical only: the old atomic flow removed its
-- version and file rows in the same transaction as completion. Never clean up or drop those rows here;
-- fail loudly if an inconsistent instance survived, so an operator can inspect before migrating.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ar_version_deletion d
        WHERE d.completed_at IS NOT NULL
          AND (
              EXISTS (SELECT 1 FROM ar_scene_version v WHERE v.id = d.version_id)
              OR EXISTS (SELECT 1 FROM ar_version_file f WHERE f.version_id = d.version_id)
          )
    ) THEN
        RAISE EXCEPTION 'V018: completed version deletion receipt still has version/file rows';
    END IF;
END $$;

CREATE TEMP TABLE ar_v018_version_map (
    version_id uuid PRIMARY KEY,
    scene_id uuid NOT NULL
);

INSERT INTO ar_v018_version_map(version_id, scene_id)
SELECT v.id,
       CASE
           WHEN s.published_version_id = v.id THEN s.id
           WHEN s.published_version_id IS NULL AND v.id = (
               SELECT v2.id FROM ar_scene_version v2
               WHERE v2.scene_id = v.scene_id
               ORDER BY v2.version_no DESC, v2.id
               LIMIT 1
           ) THEN s.id
           ELSE v.id
       END
FROM ar_scene_version v
JOIN ar_scene s ON s.id = v.scene_id;

DO $$
BEGIN
    -- Every remaining file row must map to exactly one destination scene.
    IF EXISTS (
        SELECT 1 FROM ar_version_file f
        LEFT JOIN ar_v018_version_map m ON m.version_id = f.version_id
        WHERE m.scene_id IS NULL
    ) THEN
        RAISE EXCEPTION 'V018: a version file row has no destination scene';
    END IF;
END $$;

-- A published version survives as the original scene. A scene without publication keeps its latest
-- file set but becomes disabled; empty scenes keep their current enabled flag.
UPDATE ar_scene s
SET description = COALESCE((
        SELECT v.description
        FROM ar_scene_version v
        WHERE v.id = COALESCE(s.published_version_id, (
            SELECT v2.id FROM ar_scene_version v2
            WHERE v2.scene_id = s.id
            ORDER BY v2.version_no DESC, v2.id
            LIMIT 1
        ))
    ), ''),
    request_key = s.id,
    enabled = CASE
        WHEN s.published_version_id IS NULL
             AND EXISTS (SELECT 1 FROM ar_scene_version v WHERE v.scene_id = s.id) THEN false
        ELSE s.enabled
    END;

-- Other historical versions keep their identity as separate disabled scenes.
INSERT INTO ar_scene(id, name, description, enabled, lock_version, deleted_at,
                     created_at, updated_at, request_key)
SELECT v.id,
       left(s.name, 180) || ' · 版本 ' || v.version_no,
       v.description,
       false,
       v.lock_version,
       s.deleted_at,
       v.created_at,
       v.updated_at,
       v.id
FROM ar_scene_version v
JOIN ar_v018_version_map m ON m.version_id = v.id AND m.scene_id = v.id
JOIN ar_scene s ON s.id = v.scene_id
WHERE v.id <> v.scene_id;

ALTER TABLE ar_scene ALTER COLUMN request_key SET NOT NULL;
CREATE UNIQUE INDEX ar_scene_request_key_uidx ON ar_scene(request_key);

-- File rows move directly to the scene; ids and storage keys stay untouched.
ALTER TABLE ar_version_file RENAME TO ar_scene_file;
ALTER TABLE ar_scene_file ADD COLUMN scene_id uuid;
UPDATE ar_scene_file f
SET scene_id = m.scene_id
FROM ar_v018_version_map m
WHERE m.version_id = f.version_id;
ALTER TABLE ar_scene_file ALTER COLUMN scene_id SET NOT NULL;
ALTER TABLE ar_scene_file ADD CONSTRAINT ar_scene_file_scene_fk FOREIGN KEY(scene_id) REFERENCES ar_scene(id);
ALTER TABLE ar_scene_file DROP COLUMN version_id;
CREATE UNIQUE INDEX ar_scene_file_path_uidx ON ar_scene_file(scene_id, relative_path);
ALTER INDEX ar_version_file_status_idx RENAME TO ar_scene_file_status_idx;

-- Whole-scene deletion intent, failure and minimal receipt. request_key is the scene creation key so
-- a lost response retry after physical deletion returns 410 instead of recreating the scene.
-- The receipt has no FK: it must outlive the scene row and keeps no file content.
CREATE TABLE ar_scene_deletion (
    scene_id uuid PRIMARY KEY,
    request_key uuid NOT NULL,
    actor_id bigint NOT NULL REFERENCES sys_user(user_id),
    actor_name varchar(30) NOT NULL,
    requested_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    failure_reason varchar(500),
    CHECK(completed_at IS NULL OR failure_reason IS NULL)
);
CREATE INDEX ar_scene_deletion_pending_idx ON ar_scene_deletion(scene_id) WHERE completed_at IS NULL;
CREATE INDEX ar_scene_deletion_request_idx ON ar_scene_deletion(request_key);

INSERT INTO ar_scene_deletion(scene_id, request_key, actor_id, actor_name,
                              requested_at, completed_at, failure_reason)
SELECT COALESCE(m.scene_id, d.version_id),
       COALESCE(m.scene_id, d.version_id),
       d.actor_id,
       d.actor_name,
       d.requested_at,
       d.completed_at,
       d.failure_reason
FROM ar_version_deletion d
LEFT JOIN ar_v018_version_map m ON m.version_id = d.version_id;

-- A pending receipt without a surviving scene has nothing left to delete.
UPDATE ar_scene_deletion d
SET completed_at = now(), failure_reason = NULL
WHERE d.completed_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM ar_scene s WHERE s.id = d.scene_id);

DROP TABLE ar_version_deletion;
DROP INDEX ar_scene_published_version_uidx;
ALTER TABLE ar_scene DROP CONSTRAINT ar_scene_published_version_fk;
ALTER TABLE ar_scene DROP CONSTRAINT ar_scene_published_ck;
ALTER TABLE ar_scene DROP COLUMN published_version_id;
ALTER TABLE ar_scene DROP COLUMN published_at;
ALTER TABLE ar_scene DROP COLUMN published_by_id;
ALTER TABLE ar_scene DROP COLUMN published_by_name;
DROP TABLE ar_scene_version;

DROP TABLE ar_v018_version_map;

COMMENT ON COLUMN ar_scene.request_key IS 'Scene creation idempotency key; retries with this key never create a second scene.';
COMMENT ON TABLE ar_scene_file IS 'Fixed scene file manifest; storage_key is the unchanged file UUID payload name.';
COMMENT ON TABLE ar_scene_deletion IS 'Whole-scene deletion intent and minimal idempotency receipt; request_key blocks scene resurrection.';
