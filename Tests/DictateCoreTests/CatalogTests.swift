import XCTest
@testable import DictateCore
final class CatalogTests: XCTestCase {
    func testExactlyApprovedCatalogAndImmutableArtifacts() throws {
        let models = try ModelCatalog.load()
        XCTAssertEqual(Set(models.map(\.id)), ["bark", "bark-plus", "bark-pro", "whisper-small", "whisper-turbo"])
        for m in models {
            XCTAssertFalse(m.revision.isEmpty); XCTAssertNotEqual(m.revision, "main")
            XCTAssertGreaterThan(m.bytes, 100_000_000)
            XCTAssertTrue(m.files.allSatisfy { ModelCatalog.safeRelativePath($0.path) })
            XCTAssertTrue(m.files.filter { $0.size > 1_000_000 }.allSatisfy { $0.sha256?.count == 64 })
        }
    }
    func testTraversalAndAudioBoundaries() {
        for path in ["../secret", "/etc/passwd", "a/../b", "a//b", "a\\b"] { XCTAssertFalse(ModelCatalog.safeRelativePath(path)) }
        XCTAssertTrue(ModelCatalog.safeRelativePath("Encoder.mlpackage/Data/model.mlmodel"))
        XCTAssertFalse(AudioLimits.valid([])); XCTAssertFalse(AudioLimits.valid([.nan])); XCTAssertTrue(AudioLimits.valid([0, 0.5]))
    }
}
