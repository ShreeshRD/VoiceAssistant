// swift-tools-version: 6.2
import PackageDescription
let package = Package(name: "DictateUnlimited", platforms: [.macOS(.v15)], products: [.executable(name: "DictateUnlimited", targets: ["DictateUnlimited"])], dependencies: [
    .package(path: ".dependencies/FluidAudio", traits: []),
    .package(url: "https://github.com/weichsel/ZIPFoundation.git", exact: "0.9.19"),
    .package(url: "https://github.com/argmaxinc/argmax-oss-swift.git", revision: "1bbc57cb7fe6410248a685b1c5a3c6d56adc2ed4")
], targets: [
    .target(name: "BarkSmall", dependencies: ["ZIPFoundation"], exclude: ["ATTRIBUTION.md"]),
    .target(name: "DictateCore", resources: [.process("Resources")]),
    .executableTarget(name: "DictateUnlimited", dependencies: ["DictateCore", "BarkSmall", .product(name: "FluidAudio", package: "FluidAudio"), .product(name: "WhisperKit", package: "argmax-oss-swift")]),
    .executableTarget(name: "CoreChecks", dependencies: ["DictateCore"], path: "Tests/DictateCoreChecks"),
    .testTarget(name: "DictateCoreTests", dependencies: ["DictateCore"]),
    .executableTarget(name: "BarkSmallChecks", dependencies: ["BarkSmall"], path: "Tests/BarkSmallTests", exclude: ["BarkSmallTests.swift"], sources: ["CheckMain.swift", "NumericalChecks.swift"]),
    .testTarget(name: "BarkSmallTests", dependencies: ["BarkSmall", "BarkSmallChecks"], path: "Tests/BarkSmallTests", exclude: ["CheckMain.swift", "NumericalChecks.swift"], sources: ["BarkSmallTests.swift"])
], swiftLanguageModes: [.v5])
