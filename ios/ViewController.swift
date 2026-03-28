// ViewController.swift
// Base: 3dReal (https://github.com/alexkranias/3dReal)
// Changes from 3dReal marked with // NEW

import UIKit
import AVFoundation
import AVKit          // NEW: for AVPlayerViewController
import WebKit         // NEW: for WKWebView result screen
import FirebaseStorage
import FirebaseFirestore

class ViewController: UIViewController, AVCaptureFileOutputRecordingDelegate {

    var captureSession: AVCaptureSession!
    var videoOutput: AVCaptureMovieFileOutput!
    var previewLayer: AVCaptureVideoPreviewLayer!
    var recordingStartTime: Date?
    var currentSessionId: String?           // NEW: tracks which session to listen to
    var sessionListener: ListenerRegistration? // NEW: Firestore listener handle

    @IBOutlet weak var but: UIButton!
    @IBOutlet weak var preview: UIView!

    override func viewDidLoad() {
        super.viewDidLoad()
        setupCameraSession()
    }

    func setupCameraSession() {
        // From 3dReal — unchanged
        captureSession = AVCaptureSession()
        captureSession.beginConfiguration()

        guard let videoDevice = AVCaptureDevice.default(for: .video),
              let videoInput = try? AVCaptureDeviceInput(device: videoDevice),
              captureSession.canAddInput(videoInput) else { return }

        captureSession.addInput(videoInput)

        videoOutput = AVCaptureMovieFileOutput()
        if captureSession.canAddOutput(videoOutput) {
            captureSession.addOutput(videoOutput)
        }

        previewLayer = AVCaptureVideoPreviewLayer(session: captureSession)
        previewLayer.frame = preview.bounds
        previewLayer.videoGravity = .resizeAspectFill
        preview.layer.addSublayer(previewLayer)
        previewLayer.frame = preview.layer.bounds
        preview.layer.masksToBounds = true

        captureSession.commitConfiguration()
        captureSession.startRunning()
    }

    @IBAction func recordButtonTapped(_ sender: UIButton) {
        recordingStartTime = Date()
        let outputPath = NSTemporaryDirectory() + "output.mov"
        let outputFileURL = URL(fileURLWithPath: outputPath)

        videoOutput.startRecording(to: outputFileURL, recordingDelegate: self)

        // NEW: 10 seconds instead of 2 — sports moments need more time
        DispatchQueue.main.asyncAfter(deadline: .now() + 10) {
            self.videoOutput.stopRecording()
        }
    }

    func fileOutput(_ output: AVCaptureFileOutput, didStartRecordingTo fileURL: URL, from connections: [AVCaptureConnection]) {
        print("Recording started")
    }

    func fileOutput(_ output: AVCaptureFileOutput, didFinishRecordingTo outputFileURL: URL, from connections: [AVCaptureConnection], error: Error?) {
        print("Recording finished")
        UISaveVideoAtPathToSavedPhotosAlbum(outputFileURL.path, self, #selector(video(_:didFinishSavingWithError:contextInfo:)), nil)
        uploadVideoToFirebaseStorage(videoURL: outputFileURL)
    }

    @objc func video(_ videoPath: String, didFinishSavingWithError error: Error?, contextInfo: UnsafeRawPointer) {
        if let error = error {
            print("Error saving video: \(error.localizedDescription)")
        } else {
            print("Video saved successfully.")
        }
    }

    func uploadVideoToFirebaseStorage(videoURL: URL) {
        // From 3dReal — unchanged except we save sessionId
        guard let startTime = recordingStartTime else { return }

        let dateFormatter = DateFormatter()
        dateFormatter.dateFormat = "yyyyMMddHHmmss"
        let dateString = dateFormatter.string(from: startTime)
        let baseString = String(dateString.dropLast())
        let flooredDateString = baseString + "0"

        // NEW: save session ID so we can listen for results
        self.currentSessionId = flooredDateString

        let storageRef = Storage.storage().reference()
        let videoPath = "videos/\(flooredDateString)/\(UUID().uuidString).mov"
        let videosRef = storageRef.child(videoPath)

        videosRef.putFile(from: videoURL, metadata: nil) { metadata, error in
            guard metadata != nil else {
                print("Upload error: \(error?.localizedDescription ?? "unknown")")
                return
            }
            videosRef.downloadURL { url, error in
                guard let downloadURL = url else { return }
                self.saveVideoInfoToDatabase(downloadURL: downloadURL, timestamp: startTime)

                // NEW: start listening for the result
                self.listenForResult(sessionId: flooredDateString)
            }
        }
    }

    func saveVideoInfoToDatabase(downloadURL: URL, timestamp: Date) {
        // From 3dReal — unchanged
        let db = Firestore.firestore()
        db.collection("videos").addDocument(data: [
            "url": downloadURL.absoluteString,
            "timestamp": timestamp
        ]) { error in
            if let error = error {
                print("Firestore error: \(error.localizedDescription)")
            }
        }
    }

    // NEW: listen for backend to write result_url
    func listenForResult(sessionId: String) {
        let db = Firestore.firestore()
        sessionListener = db.collection("sessions").document(sessionId)
            .addSnapshotListener { [weak self] snapshot, error in
                guard let data = snapshot?.data(),
                      let status = data["status"] as? String,
                      status == "done",
                      let resultUrl = data["result_url"] as? String else { return }

                DispatchQueue.main.async {
                    self?.showResult(urlString: resultUrl)
                }
            }
    }

    // NEW: play the orbit video when ready
    func showResult(urlString: String) {
        sessionListener?.remove()
        guard let url = URL(string: urlString) else { return }

        let player = AVPlayer(url: url)
        let playerVC = AVPlayerViewController()
        playerVC.player = player
        present(playerVC, animated: true) {
            player.play()
        }
    }
}
