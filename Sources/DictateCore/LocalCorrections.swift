// SPDX-License-Identifier: MIT
import Foundation

/// A user-authored spelling/casing correction. No recognition or automatic learning.
public struct LocalCorrection: Codable, Identifiable, Equatable, Sendable {
    public let id: UUID
    public var heard: String
    public var replacement: String

    public init(id: UUID = UUID(), heard: String, replacement: String) {
        self.id = id
        self.heard = heard.trimmingCharacters(in: .whitespacesAndNewlines)
        self.replacement = replacement.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

public enum LocalCorrections {
    public static let maximumTermLength = 120
    private static let locale = Locale(identifier: "en_US_POSIX")

    private static func key(_ text: String) -> String {
        text.precomposedStringWithCanonicalMapping.folding(options: .caseInsensitive, locale: locale)
    }

    /// Validate raw editor values before constructing an entry. Existing entries can be
    /// supplied when editing; excludingID permits retaining the edited entry's own term.
    public static func validationError(
        heard: String,
        replacement: String,
        existing: [LocalCorrection],
        excludingID: UUID? = nil
    ) -> String? {
        for value in [heard, replacement] {
            if value.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) || CharacterSet.newlines.contains($0) }) {
                return "Corrections must be a single line without control characters."
            }
        }
        let source = heard.trimmingCharacters(in: .whitespacesAndNewlines)
        let destination = replacement.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !source.isEmpty, !destination.isEmpty else { return "Enter both what was heard and its replacement." }
        guard source.count <= maximumTermLength, destination.count <= maximumTermLength else {
            return "Each correction field must contain at most \(maximumTermLength) characters."
        }
        guard !existing.contains(where: { $0.id != excludingID && key($0.heard.trimmingCharacters(in: .whitespacesAndNewlines)) == key(source) }) else {
            return "A correction for that phrase already exists."
        }
        return nil
    }

    /// Match only the original transcript, longest literal phrase first at a given
    /// position. Replacement text is never interpreted as regex syntax or reprocessed.
    public static func apply(_ text: String, entries: [LocalCorrection]) -> String {
        guard !text.isEmpty else { return text }
        var accepted: [LocalCorrection] = []
        for entry in entries {
            guard validationError(heard: entry.heard, replacement: entry.replacement, existing: accepted) == nil else { continue }
            accepted.append(LocalCorrection(id: entry.id, heard: entry.heard, replacement: entry.replacement))
        }
        guard !accepted.isEmpty else { return text }
        // Marks belong to the surrounding letter, and underscore protects identifiers.
        let wordCharacter = "[\\p{L}\\p{N}\\p{M}_]"
        let ordered = accepted.enumerated().sorted {
            let left = $0.element.heard.utf16.count, right = $1.element.heard.utf16.count
            return left == right ? $0.offset < $1.offset : left > right
        }.map(\.element)
        let alternatives = ordered.flatMap { entry -> [String] in
            let composed = entry.heard.precomposedStringWithCanonicalMapping
            let decomposed = entry.heard.decomposedStringWithCanonicalMapping
            return (composed.utf16.elementsEqual(decomposed.utf16) ? [composed] : [composed, decomposed]).map(NSRegularExpression.escapedPattern(for:))
        }
        let pattern = "(?<!" + wordCharacter + ")(?:" + alternatives.joined(separator: "|") + ")(?!" + wordCharacter + ")"
        guard let expression = try? NSRegularExpression(pattern: pattern, options: .caseInsensitive) else { return text }
        let source = text as NSString
        let replacements = Dictionary(uniqueKeysWithValues: accepted.map { (key($0.heard), $0.replacement) })
        let matches = expression.matches(in: text, range: NSRange(location: 0, length: source.length))
        let result = NSMutableString(string: text)
        for match in matches.reversed() {
            guard let replacement = replacements[key(source.substring(with: match.range))] else { continue }
            result.replaceCharacters(in: match.range, with: replacement)
        }
        return result as String
    }
}
