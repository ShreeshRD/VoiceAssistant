import XCTest
@testable import BarkSmallChecks

final class BarkSmallTests: XCTestCase {
    func testNumericNPYAndRejectUnsafeInputs() throws { try BarkSmallNumericalChecks().testNumericNPYAndRejectUnsafeInputs() }
    func testRowwiseDequantization() throws { try BarkSmallNumericalChecks().testRowwiseDequantization() }
    func testSegmentationIsContiguousBoundedAndFindsSilence() throws { try BarkSmallNumericalChecks().testSegmentationIsContiguousBoundedAndFindsSilence() }
    func testFrontendAgainstIndependentSlowDFT() throws { try BarkSmallNumericalChecks().testFrontendAgainstIndependentSlowDFT() }
    func testSilenceFeaturesRemainFinite() throws { try BarkSmallNumericalChecks().testSilenceFeaturesRemainFinite() }
    func testTDTZeroDurationIsBoundedAndBlankAdvances() throws { try BarkSmallNumericalChecks().testTDTZeroDurationIsBoundedAndBlankAdvances() }
}
