-- A content version is its fixed file list plus the editable description. Variant, segment timing,
-- transform and media roles are decided by the Unity client from the relative paths, so the
-- resource.json descriptor is no longer stored. Destructive for that column only: back up the
-- database before running this against an instance that holds versions.
ALTER TABLE ar_scene_version DROP COLUMN descriptor;
