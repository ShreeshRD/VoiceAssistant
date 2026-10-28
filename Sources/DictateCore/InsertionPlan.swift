import Foundation

/// Plans a verified replacement without joining adjacent words across dictations.
/// Selected text is replaced literally; only a zero-length insertion gets boundary spaces.
public struct InsertionPlan {
    public let insertedText: String
    public let expectedText: String
    public init?(text: String, original: String, range: NSRange) {
        let units = Array(original.utf16)
        guard !text.isEmpty, range.location >= 0, range.length >= 0,
              range.location <= units.count, range.length <= units.count - range.location else { return nil }
        func scalarBoundary(_ offset: Int) -> Bool {
            if offset == 0 || offset == units.count { return true }
            return !(0xD800...0xDBFF).contains(units[offset - 1]) || !(0xDC00...0xDFFF).contains(units[offset])
        }
        guard scalarBoundary(range.location), scalarBoundary(range.location + range.length),
              let selected = Range(range, in: original) else { return nil }
        var insertion = text
        func word(_ character: Character?) -> Bool {
            guard let character else { return false }
            return character.unicodeScalars.contains { CharacterSet.alphanumerics.contains($0) }
        }
        if range.length == 0 {
            if word(original[..<selected.lowerBound].last), word(text.first) { insertion = " " + insertion }
            if word(text.last), word(original[selected.upperBound...].first) { insertion += " " }
        }
        insertedText = insertion
        expectedText = original.replacingCharacters(in: selected, with: insertion)
    }
}
