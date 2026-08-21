import AppKit
import AVFoundation
import CoreVideo
import Foundation

let arguments = CommandLine.arguments
guard arguments.count == 5,
      let width = Int(arguments[2]),
      let height = Int(arguments[3]),
      let fps = Int32(arguments[4]) else {
    FileHandle.standardError.write(Data("usage: encode_frames output.mp4 width height fps\n".utf8))
    exit(2)
}

let outputURL = URL(fileURLWithPath: arguments[1])
try? FileManager.default.removeItem(at: outputURL)

let writer = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
let compression: [String: Any] = [
    AVVideoAverageBitRateKey: 12_000_000,
    AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
    AVVideoExpectedSourceFrameRateKey: fps,
    AVVideoMaxKeyFrameIntervalKey: fps * 2,
]
let settings: [String: Any] = [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: width,
    AVVideoHeightKey: height,
    AVVideoCompressionPropertiesKey: compression,
]
let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
input.expectsMediaDataInRealTime = false

let attributes: [String: Any] = [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
    kCVPixelBufferWidthKey as String: width,
    kCVPixelBufferHeightKey as String: height,
    kCVPixelBufferCGImageCompatibilityKey as String: true,
    kCVPixelBufferCGBitmapContextCompatibilityKey as String: true,
]
let adaptor = AVAssetWriterInputPixelBufferAdaptor(
    assetWriterInput: input,
    sourcePixelBufferAttributes: attributes
)
guard writer.canAdd(input) else {
    throw NSError(domain: "HTMLToMP4", code: 1, userInfo: [NSLocalizedDescriptionKey: "Cannot add video input"])
}
writer.add(input)
guard writer.startWriting() else {
    throw writer.error ?? NSError(domain: "HTMLToMP4", code: 2)
}
writer.startSession(atSourceTime: .zero)

func readExactly(_ count: Int) throws -> Data? {
    var result = Data()
    while result.count < count {
        let chunk = try FileHandle.standardInput.read(upToCount: count - result.count) ?? Data()
        if chunk.isEmpty {
            return result.isEmpty ? nil : result
        }
        result.append(chunk)
    }
    return result
}

func waitUntilReady() {
    while !input.isReadyForMoreMediaData {
        Thread.sleep(forTimeInterval: 0.002)
    }
}

var frameIndex: Int64 = 0
while let header = try readExactly(4) {
    guard header.count == 4 else {
        throw NSError(domain: "HTMLToMP4", code: 3, userInfo: [NSLocalizedDescriptionKey: "Truncated frame header"])
    }
    let length = header.withUnsafeBytes { raw -> UInt32 in
        raw.loadUnaligned(as: UInt32.self).bigEndian
    }
    guard let jpeg = try readExactly(Int(length)), jpeg.count == Int(length),
          let image = NSImage(data: jpeg),
          let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil),
          let pool = adaptor.pixelBufferPool else {
        throw NSError(domain: "HTMLToMP4", code: 4, userInfo: [NSLocalizedDescriptionKey: "Cannot decode frame \(frameIndex)"])
    }

    var optionalBuffer: CVPixelBuffer?
    let result = CVPixelBufferPoolCreatePixelBuffer(nil, pool, &optionalBuffer)
    guard result == kCVReturnSuccess, let buffer = optionalBuffer else {
        throw NSError(domain: "HTMLToMP4", code: 5, userInfo: [NSLocalizedDescriptionKey: "Cannot allocate pixel buffer"])
    }

    CVPixelBufferLockBaseAddress(buffer, [])
    defer { CVPixelBufferUnlockBaseAddress(buffer, []) }
    guard let base = CVPixelBufferGetBaseAddress(buffer),
          let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
          let context = CGContext(
              data: base,
              width: width,
              height: height,
              bitsPerComponent: 8,
              bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
              space: colorSpace,
              bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue
          ) else {
        throw NSError(domain: "HTMLToMP4", code: 6, userInfo: [NSLocalizedDescriptionKey: "Cannot create frame context"])
    }
    context.setFillColor(NSColor.black.cgColor)
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    context.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))

    waitUntilReady()
    let time = CMTime(value: frameIndex, timescale: fps)
    guard adaptor.append(buffer, withPresentationTime: time) else {
        throw writer.error ?? NSError(domain: "HTMLToMP4", code: 7)
    }
    frameIndex += 1
    if frameIndex % Int64(fps * 10) == 0 {
        FileHandle.standardError.write(Data("encoded \(frameIndex / Int64(fps))s\n".utf8))
    }
}

input.markAsFinished()
await writer.finishWriting()
guard writer.status == .completed else {
    throw writer.error ?? NSError(domain: "HTMLToMP4", code: 8)
}
FileHandle.standardError.write(Data("complete: \(frameIndex) frames\n".utf8))

