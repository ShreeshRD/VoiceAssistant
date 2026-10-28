import Foundation

/// Standalone numerical checks for CLT hosts without XCTest.
@main struct CheckMain {
    static func main() throws {
        #if DEBUG
        let checks = BarkSmallNumericalChecks()
        try checks.testNumericNPYAndRejectUnsafeInputs(); print("PASS testNumericNPYAndRejectUnsafeInputs")
        try checks.testRowwiseDequantization(); print("PASS testRowwiseDequantization")
        try checks.testSegmentationIsContiguousBoundedAndFindsSilence(); print("PASS testSegmentationIsContiguousBoundedAndFindsSilence")
        try checks.testFrontendAgainstIndependentSlowDFT(); print("PASS testFrontendAgainstIndependentSlowDFT")
        try checks.testSilenceFeaturesRemainFinite(); print("PASS testSilenceFeaturesRemainFinite")
        try checks.testTDTZeroDurationIsBoundedAndBlankAdvances(); print("PASS testTDTZeroDurationIsBoundedAndBlankAdvances")
        print("6 standalone checks passed. This is not XCTest execution.")
        #else
        print("Run these checks with swift run BarkSmallChecks (debug configuration).")
        #endif
    }
}
