import AppKit
import AVFoundation
import CoreMedia
import Foundation

guard CommandLine.arguments.count == 3 else {
    FileHandle.standardError.write(Data("usage: verify_video input.mp4 frames-directory\n".utf8))
    exit(2)
}

let videoURL = URL(fileURLWithPath: CommandLine.arguments[1])
let framesURL = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
try FileManager.default.createDirectory(at: framesURL, withIntermediateDirectories: true)

let asset = AVURLAsset(url: videoURL)
let duration = try await asset.load(.duration)
let videoTracks = try await asset.loadTracks(withMediaType: .video)
guard let track = videoTracks.first else {
    throw NSError(domain: "VerifyVideo", code: 1, userInfo: [NSLocalizedDescriptionKey: "No video track"])
}
let size = try await track.load(.naturalSize)
let transform = try await track.load(.preferredTransform)
let frameRate = try await track.load(.nominalFrameRate)
let transformed = CGRect(origin: .zero, size: size).applying(transform)

print("duration_seconds=\(String(format: "%.3f", CMTimeGetSeconds(duration)))")
print("display_width=\(Int(abs(transformed.width)))")
print("display_height=\(Int(abs(transformed.height)))")
print("nominal_fps=\(String(format: "%.3f", frameRate))")
print("video_tracks=\(videoTracks.count)")

let generator = AVAssetImageGenerator(asset: asset)
generator.appliesPreferredTrackTransform = true
generator.requestedTimeToleranceBefore = .zero
generator.requestedTimeToleranceAfter = .zero
let sampleSeconds: [Double] = [0.5, 25.0, 60.0, 85.0, 100.0, 118.0, 132.0, 141.5]

for (index, seconds) in sampleSeconds.enumerated() {
    let time = CMTime(seconds: seconds, preferredTimescale: 600)
    let cgImage = try generator.copyCGImage(at: time, actualTime: nil)
    let bitmap = NSBitmapImageRep(cgImage: cgImage)
    guard let png = bitmap.representation(using: .png, properties: [:]) else {
        throw NSError(domain: "VerifyVideo", code: 2)
    }
    let output = framesURL.appendingPathComponent(String(format: "frame-%02d-%06.1fs.png", index + 1, seconds))
    try png.write(to: output)
    print("sample_frame=\(output.path)")
}
