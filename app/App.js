import React, { useState, useRef, useEffect } from 'react';
import {
  View, TouchableOpacity, Text, StyleSheet,
  ActivityIndicator, Alert, StatusBar,
} from 'react-native';
import { CameraView, useCameraPermissions, useMicrophonePermissions } from 'expo-camera';
import { Video, ResizeMode } from 'expo-av';
import { initializeApp } from 'firebase/app';
import { getStorage, ref as storageRef, uploadBytes } from 'firebase/storage';
import { getFirestore, doc, onSnapshot } from 'firebase/firestore';

// ── Firebase config — fill these in (Firebase Console → Project Settings → Web app) ──
const FIREBASE_CONFIG = {
  apiKey:            "REPLACE_ME",
  authDomain:        "REPLACE_ME",
  projectId:         "REPLACE_ME",
  storageBucket:     "REPLACE_ME",
  messagingSenderId: "REPLACE_ME",
  appId:             "REPLACE_ME",
};

const firebaseApp = initializeApp(FIREBASE_CONFIG);
const storage     = getStorage(firebaseApp);
const db          = getFirestore(firebaseApp);

// ── Helpers ───────────────────────────────────────────────────────────────────

// Produces the same timestamp format as 3dReal's Swift backend listener
function makeSessionId() {
  const now = new Date();
  const p = n => String(n).padStart(2, '0');
  const s = `${now.getFullYear()}${p(now.getMonth() + 1)}${p(now.getDate())}` +
            `${p(now.getHours())}${p(now.getMinutes())}${p(now.getSeconds())}`;
  return s.slice(0, -1) + '0'; // floor last digit — matches backend blob.name length == 62
}

function randomId() {
  return Math.random().toString(36).slice(2, 10);
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [cameraPermission, requestCameraPermission] = useCameraPermissions();
  const [micPermission,    requestMicPermission]    = useMicrophonePermissions();

  // phase: 'idle' | 'recording' | 'uploading' | 'processing' | 'done'
  const [phase,      setPhase]      = useState('idle');
  const [resultUrl,  setResultUrl]  = useState(null);
  const [countdown,  setCountdown]  = useState(10);

  const cameraRef    = useRef(null);
  const listenerRef  = useRef(null); // Firestore unsubscribe handle

  useEffect(() => {
    requestCameraPermission();
    requestMicPermission();
    return () => listenerRef.current?.(); // cleanup listener on unmount
  }, []);

  // ── Record ──────────────────────────────────────────────────────────────────

  async function startRecording() {
    if (!cameraRef.current) return;
    setPhase('recording');
    setCountdown(10);

    const interval = setInterval(() => {
      setCountdown(c => {
        if (c <= 1) { clearInterval(interval); return 0; }
        return c - 1;
      });
    }, 1000);

    const video = await cameraRef.current.recordAsync({ maxDuration: 10 });
    clearInterval(interval);
    await uploadVideo(video.uri);
  }

  function stopEarly() {
    cameraRef.current?.stopRecording();
  }

  // ── Upload ──────────────────────────────────────────────────────────────────

  async function uploadVideo(uri) {
    setPhase('uploading');
    try {
      const sessionId = makeSessionId();
      const path      = `videos/${sessionId}/${randomId()}.mov`;

      const response = await fetch(uri);
      const blob     = await response.blob();
      await uploadBytes(storageRef(storage, path), blob);

      setPhase('processing');
      listenForResult(sessionId);
    } catch (e) {
      Alert.alert('Upload failed', e.message);
      setPhase('idle');
    }
  }

  // ── Listen for backend result ───────────────────────────────────────────────

  function listenForResult(sessionId) {
    const docRef = doc(db, 'sessions', sessionId);
    listenerRef.current = onSnapshot(docRef, snapshot => {
      const data = snapshot.data();
      if (data?.status === 'done' && data?.result_url) {
        setResultUrl(data.result_url);
        setPhase('done');
        listenerRef.current?.();
      }
    });
  }

  function reset() {
    setPhase('idle');
    setResultUrl(null);
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  if (!cameraPermission?.granted || !micPermission?.granted) {
    return (
      <View style={s.center}>
        <Text style={s.label}>Camera and microphone access needed</Text>
        <TouchableOpacity style={s.btn} onPress={() => {
          requestCameraPermission();
          requestMicPermission();
        }}>
          <Text style={s.btnText}>Grant permissions</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (phase === 'done' && resultUrl) {
    return (
      <View style={s.container}>
        <Video
          source={{ uri: resultUrl }}
          style={s.video}
          resizeMode={ResizeMode.CONTAIN}
          shouldPlay
          isLooping
          useNativeControls
        />
        <TouchableOpacity style={[s.btn, s.resetBtn]} onPress={reset}>
          <Text style={s.btnText}>Record another</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (phase === 'uploading' || phase === 'processing') {
    return (
      <View style={s.center}>
        <ActivityIndicator size="large" color="#fff" />
        <Text style={s.label}>
          {phase === 'uploading'
            ? 'Uploading video...'
            : 'Gemini is finding the peak moment...'}
        </Text>
      </View>
    );
  }

  // idle or recording — show camera
  return (
    <View style={s.container}>
      <StatusBar barStyle="light-content" />
      <CameraView ref={cameraRef} style={s.camera} mode="video" facing="back">
        <View style={s.controls}>
          {phase === 'recording' ? (
            <>
              <Text style={s.countdown}>{countdown}</Text>
              <TouchableOpacity style={s.stopBtn} onPress={stopEarly}>
                <View style={s.stopIcon} />
              </TouchableOpacity>
            </>
          ) : (
            <TouchableOpacity style={s.recordBtn} onPress={startRecording}>
              <View style={s.recordIcon} />
            </TouchableOpacity>
          )}
        </View>
      </CameraView>
    </View>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const s = StyleSheet.create({
  container:  { flex: 1, backgroundColor: '#000' },
  center:     { flex: 1, backgroundColor: '#000', alignItems: 'center', justifyContent: 'center', gap: 20 },
  camera:     { flex: 1 },
  video:      { flex: 1 },
  controls:   { flex: 1, justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 60 },
  countdown:  { color: '#fff', fontSize: 48, fontWeight: 'bold', marginBottom: 20 },
  label:      { color: '#fff', fontSize: 16, textAlign: 'center', paddingHorizontal: 40 },
  recordBtn:  { width: 72, height: 72, borderRadius: 36, borderWidth: 4, borderColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  recordIcon: { width: 52, height: 52, borderRadius: 26, backgroundColor: '#e00' },
  stopBtn:    { width: 72, height: 72, borderRadius: 36, borderWidth: 4, borderColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  stopIcon:   { width: 30, height: 30, backgroundColor: '#fff', borderRadius: 4 },
  btn:        { backgroundColor: '#e00', paddingHorizontal: 32, paddingVertical: 14, borderRadius: 8 },
  resetBtn:   { margin: 20 },
  btnText:    { color: '#fff', fontSize: 16, fontWeight: '600' },
});
