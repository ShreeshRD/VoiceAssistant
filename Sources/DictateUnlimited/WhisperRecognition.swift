// LocalWhisperTokenizer below adapts Argmax WhisperKit v1.1.1 Models.swift.
// Copyright (c) 2024 Argmax, Inc. MIT licence retained in Resources/Notices/WhisperKit-LICENSE.txt.
// Other integration code: Copyright (c) 2026 DOO MADE, MIT.
import Foundation
import WhisperKit
import NaturalLanguage

/// Loads only the complete, app-owned model folder. Missing or corrupt tokenizers
/// fail locally: WhisperKit's default tokenizer loader otherwise falls back to Hub.
private final class OfflineWhisperKit: WhisperKit {
    override func loadTokenizerIfNeeded() async throws {
        guard tokenizer == nil else { return }
        guard let root = modelFolder,
              let vocabularySize = textDecoder.logitsSize,
              let encoderSize = audioEncoder.embedSize,
              (vocabularySize == 51865 && encoderSize == 768)
                || (vocabularySize == 51866 && encoderSize == 1280) else {
            throw AppError("Unsupported Whisper model. Import a multilingual small or large-v3-compatible WhisperKit export.")
        }
        do {
        let local = try await AutoTokenizerWrapper.from(modelFolder: root)
        let wrapped = try LocalWhisperTokenizer(local)
        guard wrapped.convertTokenToId("<|en|>") == 50259,
              wrapped.convertTokenToId("<|ko|>") == 50264,
              wrapped.convertTokenToId("<|endoftext|>") == 50257,
              wrapped.convertTokenToId("<|transcribe|>") == (vocabularySize == 51866 ? 50360 : 50359) else {
            throw AppError("The local tokenizer does not match this multilingual Whisper model.")
        }
        textDecoder.isModelMultilingual = true
        tokenizer = wrapped
        } catch {
            throw AppError("Local tokenizer is invalid or incompatible. Re-download this model or import a complete matching folder. No network fallback was attempted.")
        }
    }
}

final class WhisperRecognition {
    private let pipeline: OfflineWhisperKit

    init(root: URL) async throws {
        // A tokenizer must be provided with every import/download. Never use a
        // user's global tokenizer cache or a remote fallback.
        for name in ["tokenizer.json", "tokenizer_config.json"] {
            guard FileManager.default.fileExists(atPath: root.appendingPathComponent(name).path) else {
                throw AppError("Missing \(name). Import a complete WhisperKit model folder.")
            }
        }
        let config = WhisperKitConfig(
            modelFolder: root.path,
            tokenizerFolder: root,
            verbose: false,
            prewarm: false,
            load: true,
            download: false
        )
        pipeline = try await OfflineWhisperKit(config)
        try Task.checkCancellation()
    }

    func transcribe(_ samples: [Float], language: String?) async throws -> String {
        try Task.checkCancellation()
        // A digital-silence buffer cannot contain speech; do not decode it.
        guard samples.contains(where: { $0 != 0 }) else { return "" }
        if let language, pipeline.tokenizer?.convertTokenToId("<|\(language)|>") == nil {
            throw AppError("This Whisper model does not support the selected language.")
        }
        let options = DecodingOptions(
            verbose: false,
            task: .transcribe,
            language: language,
            usePrefillPrompt: true,
            detectLanguage: language == nil,
            skipSpecialTokens: true,
            withoutTimestamps: false,
            wordTimestamps: false,
            concurrentWorkerCount: 1,
            chunkingStrategy: .vad
        )
        let results = try await pipeline.transcribe(audioArray: samples, decodeOptions: options)
        try Task.checkCancellation()
        return results.map(\.text).joined(separator: " ").trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

// Adapted from Argmax WhisperKit v1.1.1 Models.swift (MIT, copyright 2024 Argmax).
// Its tokenizer-wrapper initializer is internal. Keep the upstream word grouping
// while constructing the tokenizer through the public, strictly local factory.
private final class LocalWhisperTokenizer: WhisperTokenizer {
    let tokenizer: TokenizerWrapper
    let tokenizerFolder: URL?
    public let specialTokens: SpecialTokens
    public let allLanguageTokens: Set<Int>

    public func encode(text: String) -> [Int] {
        tokenizer.encode(text: text)
    }

    public func decode(tokens: [Int]) -> String {
        tokenizer.decode(tokens: tokens)
    }

    public func convertTokenToId(_ token: String) -> Int? {
        tokenizer.convertTokenToId(token)
    }

    public func convertIdToToken(_ id: Int) -> String? {
        tokenizer.convertIdToToken(id)
    }

    /// Initializes a WhisperTokenizer wrapper with the provided tokenizer and optional folder location.
    ///
    /// This initializer sets up the tokenizer wrapper with special tokens and language token mappings
    /// required for Whisper decoding. The tokenizer folder parameter is stored for reference
    /// but does not affect the tokenizer's functionality.
    ///
    /// - Parameters:
    ///   - tokenizer: The underlying tokenizer implementation that handles text encoding/decoding
    ///   - tokenizerFolder: Optional URL representing the folder location where the tokenizer
    ///     files are stored. This is kept for reference purposes only and does not influence
    ///     tokenizer behavior or operations.
    ///
    /// - Note: Special tokens are automatically detected from the tokenizer vocabulary, with
    ///   fallback to default values if tokens are not found. Language tokens are identified
    ///   by matching the pattern `<|language|>` against the tokenizer's vocabulary.
    init(_ tokenizer: TokenizerWrapper, at tokenizerFolder: URL? = nil) throws {
        for token in ["<|endoftext|>", "<|en|>", "<|ko|>", "<|nospeech|>", "<|notimestamps|>", "<|startofprev|>", "<|startoftranscript|>", "<|0.00|>", "<|transcribe|>", "<|translate|>"] {
            guard tokenizer.convertTokenToId(token) != nil else { throw AppError("Missing Whisper tokenizer control token: \(token)") }
        }
        let specialTokens = SpecialTokens(
            endToken: tokenizer.convertTokenToId("<|endoftext|>") ?? Self.defaultEndToken,
            englishToken: tokenizer.convertTokenToId("<|en|>") ?? Self.defaultEnglishToken,
            noSpeechToken: tokenizer.convertTokenToId("<|nospeech|>") ?? Self.defaultNoSpeechToken,
            noTimestampsToken: tokenizer.convertTokenToId("<|notimestamps|>") ?? Self.defaultNoTimestampsToken,
            specialTokenBegin: tokenizer.convertTokenToId("<|endoftext|>") ?? Self.defaultSpecialTokenBegin,
            startOfPreviousToken: tokenizer.convertTokenToId("<|startofprev|>") ?? Self.defaultStartOfPreviousToken,
            startOfTranscriptToken: tokenizer.convertTokenToId("<|startoftranscript|>") ?? Self.defaultStartOfTranscriptToken,
            timeTokenBegin: tokenizer.convertTokenToId("<|0.00|>") ?? Self.defaultTimeTokenBegin,
            transcribeToken: tokenizer.convertTokenToId("<|transcribe|>") ?? Self.defaultTranscribeToken,
            translateToken: tokenizer.convertTokenToId("<|translate|>") ?? Self.defaultTranslateToken,
            whitespaceToken: tokenizer.convertTokenToId(" ") ?? Self.defaultWhitespaceToken
        )
        self.tokenizer = tokenizer
        self.tokenizerFolder = tokenizerFolder
        self.specialTokens = specialTokens
        self.allLanguageTokens = Set(
            Constants.languages
                .compactMap { tokenizer.convertTokenToId("<|\($0.value)|>") }
                .filter { $0 > specialTokens.specialTokenBegin }
        )
    }

    private func splitTokensOnUnicode(tokens: [Int]) -> (words: [String], wordTokens: [[Int]]) {
        let decodedFull = tokenizer.decode(tokens: tokens)
        let replacementString = "\u{fffd}"

        var words: [String] = []
        var wordTokens: [[Int]] = []
        var currentTokens: [Int] = []
        var unicodeOffset = 0

        for token in tokens {
            currentTokens.append(token)
            let decoded = tokenizer.decode(tokens: currentTokens)

            var hasUnicodeInFullString = false
            if let range = decoded.range(of: replacementString) {
                let offset = decoded.distance(from: decoded.startIndex, to: range.lowerBound)
                if offset < decodedFull.count {
                    let index = decodedFull.index(decodedFull.startIndex, offsetBy: offset)
                    hasUnicodeInFullString = decodedFull[index] == "\u{fffd}"
                }
            }

            if !decoded.contains(replacementString) || hasUnicodeInFullString {
                words.append(decoded)
                wordTokens.append(currentTokens)
                currentTokens = []
                unicodeOffset += decoded.count
            }
        }

        return (words, wordTokens)
    }

    private func splitTokensOnSpaces(tokens: [Int]) -> (words: [String], wordTokens: [[Int]]) {
        let (subwords, subwordTokensList) = splitTokensOnUnicode(tokens: tokens)
        var words: [String] = []
        var wordTokens: [[Int]] = []

        for (subword, subwordTokens) in zip(subwords, subwordTokensList) {
            let special = subwordTokens.first! >= specialTokens.specialTokenBegin
            let withSpace = subword.hasPrefix(" ")
            var punctuation = false
            if let strippedSubword = UnicodeScalar(subword.trimmingCharacters(in: .whitespaces)) {
                punctuation = CharacterSet.punctuationCharacters.contains(strippedSubword)
            }
            if special || withSpace || punctuation || words.isEmpty {
                words.append(subword)
                wordTokens.append(subwordTokens)
            } else {
                words[words.count - 1] += subword
                wordTokens[words.count - 1].append(contentsOf: subwordTokens)
            }
        }

        return (words, wordTokens)
    }

    private func isPunctuation(_ text: String, tokenRange: Range<String.Index>, tag: NLTag?) -> Bool {
        let punctuationCharacters = CharacterSet.punctuationCharacters
        let token = String(text[tokenRange])
        if let tag = tag, tag == .punctuation {
            return true
        } else if token.unicodeScalars.allSatisfy({ punctuationCharacters.contains($0) }) {
            return true
        }
        return false
    }

    /// Decodes token ids into individual words and per-word subtokens
    /// - Parameter tokenIds: Array of tokens to decode and then split
    /// - Returns: Tuple containing and array of the split words and all tokens for each word
    public func splitToWordTokens(tokenIds: [Int]) -> (words: [String], wordTokens: [[Int]]) {
        let decodedWords = tokenizer.decode(tokens: tokenIds.filter { $0 < specialTokens.specialTokenBegin })

        // Detect language of input text
        let recognizer = NLLanguageRecognizer()
        recognizer.processString(decodedWords)
        // NLLanguage raw values are BCP-47 tags ("zh-Hans", "zh-Hant"), while the
        // no-space-language list below uses Whisper's ISO 639-1 style codes ("zh").
        // Normalize via Locale so both Chinese variants match (matches openai/whisper,
        // which checks its decoding language code directly).
        let languageCode = recognizer.dominantLanguage.flatMap {
            Locale(identifier: $0.rawValue).language.languageCode?.identifier
        }

        if ["zh", "ja", "th", "lo", "my", "yue"].contains(languageCode) {
            return splitTokensOnUnicode(tokens: tokenIds)
        } else {
            return splitTokensOnSpaces(tokens: tokenIds)
        }
    }
}

extension LocalWhisperTokenizer {
    /// Default values for each token, using base vocab
    static var defaultWhitespaceToken: Int { 220 }
    static var defaultSpecialTokenBegin: Int { 50257 }
    static var defaultEndToken: Int { 50257 }
    static var defaultStartOfPreviousToken: Int { 50361 }
    static var defaultStartOfTranscriptToken: Int { 50258 }
    static var defaultEnglishToken: Int { 50259 }
    static var defaultTranscribeToken: Int { 50359 }
    static var defaultTranslateToken: Int { 50358 }
    static var defaultNoSpeechToken: Int { 50362 }
    static var defaultNoTimestampsToken: Int { 50363 }
    static var defaultTimeTokenBegin: Int { 50364 }
}

