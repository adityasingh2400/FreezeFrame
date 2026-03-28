# BUILD PLAN — Gemini Hackathon

## What we're building
Fork of 3dReal. User records a sports moment → Gemini finds the peak frame → COLMAP + NeRF reconstructs it in 3D → orbit video plays back in app.

## Flow
```
iPhone records video
       ↓
Firebase Storage upload
       ↓
Backend detects new video
       ↓
Gemini Flash → finds peak moment → trims video to ±3s
       ↓
nerfstudio (COLMAP + nerfacto) → orbit.mp4
       ↓
orbit.mp4 uploaded to Firebase Storage
Firestore: sessions/{id}/status = "done", result_url = "..."
       ↓
iOS app listener fires → plays orbit.mp4
```

---

## Person A — iOS (Swift)
**Base: ios/ViewController.swift + ios/AppDelegate.swift (from 3dReal)**

### What to change from 3dReal
1. Recording duration: change 2s → 10s (sports moments need more time)
2. After upload: save the session ID and start listening to Firestore
3. When status == "done": open result_url in a WKWebView/AVPlayer

### Files
- `ios/ViewController.swift` — see file, changes marked with `// NEW`
- `ios/AppDelegate.swift` — copy as-is from 3dReal
- `ios/SceneDelegate.swift` — copy as-is from 3dReal
- `ios/Podfile` — copy from 3dReal, add WebKit pod

### Steps
- 0:00 Clone 3dReal, swap Firebase config (GoogleService-Info.plist)
- 0:15 Get camera recording + upload working (already works in 3dReal)
- 0:30 Add Firestore listener for result (see ViewController.swift `// NEW` sections)
- 1:00 Add result screen (AVPlayerViewController for orbit video)
- 1:30 Test end-to-end with Person B

---

## Person B — Backend (Python)
**Base: backend/server.py (from 3dReal's server_to_nerf.py)**

### What to change from 3dReal
1. Add Gemini peak moment detection before COLMAP
2. Replace instant-ngp.exe (Windows) with nerfstudio (Linux/RunPod)
3. Upload orbit.mp4 result + write to Firestore when done

### Files
- `backend/server.py` — see file, new sections marked with `# NEW`
- `backend/requirements.txt` — updated deps

### Steps
- 0:00 SSH into RunPod, `pip install nerfstudio google-generativeai` (runs in background ~5 min)
- 0:15 Copy server.py to RunPod, add your Firebase service account + Gemini API key
- 0:30 Test Gemini peak moment function on a sample video
- 0:45 **START PRE-RUN**: run full pipeline on a pre-recorded sports clip now (takes ~15 min on A100)
- 1:00 Test nerfstudio render output
- 1:30 Connect to Person A's app, test full loop

---

## Firestore schema
```
sessions/{sessionId}/
  status:     "processing" | "done"
  result_url: "https://firebasestorage..."   ← orbit video download URL
```
sessionId = the timestamp string from the upload path (e.g. "202403171406530")

---

## Demo fallback
nerfstudio takes ~15 min on A100. Person B starts a pre-run at minute 45.
For the live demo, tap "Load Demo" to show the pre-computed result instantly.
