package com.ruoyi.ar.support;

import static org.junit.jupiter.api.Assertions.*;

import java.text.Normalizer;
import java.util.List;
import org.junit.jupiter.api.Test;

class RelativePathTest {
    @Test void keepsTopLevelFolderAndChineseNames() {
        assertEquals("场景A/models/a.bundle", RelativePath.normalizeOne("场景A/models/a.bundle"));
        assertEquals("a.bundle", RelativePath.fileName("场景A/models/a.bundle"));
    }

    @Test void rejectsTraversalAbsoluteAndUnsafeNames() {
        assertThrows(IllegalArgumentException.class, () -> RelativePath.normalizeOne("/abs/a.bin"));
        assertThrows(IllegalArgumentException.class, () -> RelativePath.normalizeOne("C:/windows/a.bin"));
        assertThrows(IllegalArgumentException.class, () -> RelativePath.normalizeOne("a/../b.bin"));
        assertThrows(IllegalArgumentException.class, () -> RelativePath.normalizeOne("a\\b.bin"));
        assertThrows(IllegalArgumentException.class, () -> RelativePath.normalizeOne("a/CON.bin"));
        assertThrows(IllegalArgumentException.class, () -> RelativePath.normalizeOne("a/b.bin "));
        assertThrows(IllegalArgumentException.class, () -> RelativePath.normalizeOne("a/b.bin."));
        assertThrows(IllegalArgumentException.class, () -> RelativePath.normalizeOne("a/\u0001.bin"));
    }

    @Test void rejectsDuplicatesPrefixConflictsAndCaseCollisions() {
        assertEquals(List.of("dir/a.bin", "dir/b.bin"), RelativePath.normalizeAll(List.of("dir/a.bin", "dir/b.bin")));
        assertThrows(IllegalArgumentException.class, () -> RelativePath.normalizeAll(List.of("a.bin", "a.bin")));
        assertThrows(IllegalArgumentException.class, () -> RelativePath.normalizeAll(List.of("a.bin", "A.bin")));
        assertThrows(IllegalArgumentException.class, () -> RelativePath.normalizeAll(List.of("a", "a/b.bin")));
        assertThrows(IllegalArgumentException.class, () -> RelativePath.normalizeAll(List.of("root/A", "root/a/b.bin")));
        String nfd = Normalizer.normalize("café/a.bin", Normalizer.Form.NFD);
        String nfc = Normalizer.normalize("café/a.bin", Normalizer.Form.NFC);
        if (!nfd.equals(nfc)) {
            assertThrows(IllegalArgumentException.class, () -> RelativePath.normalizeAll(List.of(nfd, nfc)));
        }
    }

    @Test void safeExportPathKeepsValidNamesAndRewritesReserved() {
        var id = java.util.UUID.fromString("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee");
        assertEquals("keep.bin", RelativePath.safeExportPath("keep.bin", id));
        assertEquals("scene/models/a.bin", RelativePath.safeExportPath("scene/models/a.bin", id));
        assertEquals("export-aaaaaaaa.txt", RelativePath.safeExportPath("CON.txt", id));
        assertEquals("report_2026.txt", RelativePath.safeExportPath("report:2026.txt", id));
        assertEquals("dir/a.bin", RelativePath.normalizeOne("dir/a.bin"));
    }
}
