// NumPy container reader written for Dictate Unlimited. Original code: MIT.
import Foundation
import ZIPFoundation

public enum SmallBarkError: Error, LocalizedError, Sendable {
    case invalid(String)
    public var errorDescription: String? {
        switch self { case .invalid(let message): return "Bark model: \(message)" }
    }
}

struct Tensor: Sendable {
    let shape: [Int]
    let values: [Float]
}

/// Reads only numeric, C-order NPY arrays. No pickle/object loading or filesystem extraction.
struct ArrayArchive {
    let arrays: [String: Tensor]
    init(arrays: [String: Tensor]) { self.arrays = arrays }
    init(url: URL) throws {
        let archive = try Archive(url: url, accessMode: .read)
        var result: [String: Tensor] = [:]
        var total = 0
        var decodedCount = 0
        for entry in archive {
            guard entry.path.hasSuffix(".npy"), !entry.path.contains("/"), entry.type == .file else {
                throw SmallBarkError.invalid("Unexpected decoder archive entry: \(entry.path)")
            }
            guard entry.uncompressedSize <= 128 * 1024 * 1024 else {
                throw SmallBarkError.invalid("Decoder array exceeds the memory budget")
            }
            total += Int(entry.uncompressedSize)
            guard total <= 256 * 1024 * 1024 else { throw SmallBarkError.invalid("Decoder archive is too large") }
            var data = Data()
            data.reserveCapacity(Int(entry.uncompressedSize))
            let crc = try archive.extract(entry) { chunk in
                guard data.count + chunk.count <= Int(entry.uncompressedSize) else {
                    throw SmallBarkError.invalid("Invalid decoder array size")
                }
                data.append(chunk)
            }
            guard crc == entry.checksum else { throw SmallBarkError.invalid("Decoder archive checksum mismatch") }
            let key = String(entry.path.dropLast(4))
            guard result[key] == nil else { throw SmallBarkError.invalid("Duplicate decoder array: \(key)") }
            let tensor = try Self.npy(data)
            decodedCount += tensor.values.count
            guard decodedCount <= 64 * 1024 * 1024 else { throw SmallBarkError.invalid("Decoded weights exceed memory budget") }
            result[key] = tensor
        }
        arrays = result
    }

    static func npy(_ data: Data) throws -> Tensor {
        let bytes = [UInt8](data)
        guard bytes.count >= 10, Array(bytes.prefix(6)) == [0x93, 0x4e, 0x55, 0x4d, 0x50, 0x59] else {
            throw SmallBarkError.invalid("Invalid NPY header")
        }
        let major = Int(bytes[6])
        let prefix: Int
        let length: Int
        if major == 1 {
            prefix = 10; length = Int(bytes[8]) | Int(bytes[9]) << 8
        } else if major == 2 || major == 3 {
            guard bytes.count >= 12 else { throw SmallBarkError.invalid("Truncated NPY header") }
            prefix = 12
            length = (0..<4).reduce(0) { $0 | Int(bytes[8 + $1]) << (8 * $1) }
        } else { throw SmallBarkError.invalid("Unsupported NPY version") }
        guard length <= 65_536, prefix + length <= bytes.count,
              let header = String(bytes: bytes[prefix..<(prefix + length)], encoding: .utf8) else {
            throw SmallBarkError.invalid("Invalid NPY header length or encoding")
        }
        func capture(_ pattern: String) throws -> String {
            let regex = try NSRegularExpression(pattern: pattern)
            guard let m = regex.firstMatch(in: header, range: NSRange(header.startIndex..., in: header)),
                  let range = Range(m.range(at: 1), in: header) else { throw SmallBarkError.invalid("Incomplete NPY header") }
            return String(header[range])
        }
        let dtype = try capture("['\"]descr['\"]\\s*:\\s*['\"]([^'\"]+)['\"]")
        let order = try capture("['\"]fortran_order['\"]\\s*:\\s*(True|False)")
        guard order == "False" else { throw SmallBarkError.invalid("Fortran-order NPY is unsupported") }
        let rawShape = try capture("['\"]shape['\"]\\s*:\\s*\\(([^)]*)\\)")
        let components = rawShape.split(separator: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        var shape: [Int] = []
        var count = 1
        for component in components {
            guard let dimension = Int(component), dimension >= 0, dimension <= 100_000_000 else {
                throw SmallBarkError.invalid("Invalid NPY dimension")
            }
            let product = count.multipliedReportingOverflow(by: dimension)
            guard !product.overflow, product.partialValue <= 32 * 1024 * 1024 else { throw SmallBarkError.invalid("NPY shape exceeds budget") }
            count = product.partialValue; shape.append(dimension)
        }
        let stride: Int
        switch dtype {
        case "|i1", "<i1": stride = 1
        case "<f2": stride = 2
        case "<f4": stride = 4
        default: throw SmallBarkError.invalid("Unsupported NPY dtype \(dtype)")
        }
        let offset = prefix + length
        guard count * stride == bytes.count - offset else { throw SmallBarkError.invalid("NPY payload does not match shape") }
        var values = [Float](); values.reserveCapacity(count)
        for i in 0..<count {
            let p = offset + i * stride
            switch stride {
            case 1: values.append(Float(Int8(bitPattern: bytes[p])))
            case 2: values.append(Float(Float16(bitPattern: UInt16(bytes[p]) | UInt16(bytes[p + 1]) << 8)))
            default:
                let bits = UInt32(bytes[p]) | UInt32(bytes[p+1]) << 8 | UInt32(bytes[p+2]) << 16 | UInt32(bytes[p+3]) << 24
                values.append(Float(bitPattern: bits))
            }
        }
        guard values.allSatisfy(\.isFinite) else { throw SmallBarkError.invalid("Non-finite decoder weight") }
        return Tensor(shape: shape, values: values)
    }

    func tensor(_ name: String) throws -> Tensor {
        guard let result = arrays[name] else { throw SmallBarkError.invalid("Missing array \(name)") }
        return result
    }
    func weight(_ name: String) throws -> Tensor {
        if let q = arrays[name + ".q"] {
            let scales = try tensor(name + ".s")
            guard q.shape.count == 2, scales.shape == [q.shape[0]] else {
                throw SmallBarkError.invalid("Invalid quantization shape for \(name)")
            }
            let columns = q.shape[1]
            return Tensor(shape: q.shape, values: q.values.enumerated().map { $0.element * scales.values[$0.offset / columns] })
        }
        return try tensor(name)
    }
}
