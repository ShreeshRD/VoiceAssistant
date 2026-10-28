import Foundation

public enum TranscriptionLanguage {
    /// Explicit choices for the preview; auto detection covers the model's other languages.
    public static let options: [(code:String,name:String)] = [
        ("auto","Auto-detect"), ("en","English"), ("ko","한국어 — Korean"),
        ("ja","日本語 — Japanese"), ("zh","中文 — Chinese"), ("es","Español — Spanish"),
        ("fr","Français — French"), ("de","Deutsch — German"), ("it","Italiano — Italian"),
        ("pt","Português — Portuguese"), ("hi","हिन्दी — Hindi"), ("ar","العربية — Arabic"),
        ("ru","Русский — Russian"), ("vi","Tiếng Việt — Vietnamese"), ("th","ไทย — Thai"),
        ("id","Bahasa Indonesia — Indonesian"), ("nl","Nederlands — Dutch"), ("tr","Türkçe — Turkish")
    ]
    public static func valid(_ code:String) -> Bool { options.contains { $0.code == code } }
}
