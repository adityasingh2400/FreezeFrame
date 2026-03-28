import React, { useState, useEffect, useCallback } from 'react';
import SeatMap from './SeatMap';
import VideoPanel from './VideoPanel';
import UploadModal from './UploadModal';
import { useVeo } from './useVeo';

const API = import.meta.env.VITE_API_BASE || '';

export default function App() {
  const [seats, setSeats] = useState([]);
  const [selectedSection, setSelectedSection] = useState(null);
  const [showUpload, setShowUpload] = useState(false);
  const veo = useVeo();

  // Load all videos on mount
  useEffect(() => {
    fetch(`${API}/api/videos`)
      .then(r => r.json())
      .then(d => setSeats(d.seats || []))
      .catch(() => {});
  }, []);

  const selectedSeat = seats.find(s => s.seatId === String(selectedSection)) || null;

  const handleSectionClick = useCallback((section) => {
    if (selectedSection !== section) {
      setSelectedSection(section);
      veo.reset();
    }
  }, [selectedSection, veo]);

  const handleGenerate = useCallback(async () => {
    if (!selectedSection) return;
    try {
      const videoUrl = await veo.generate(String(selectedSection), selectedSection, 1);
      // Refresh seats list to include new AI seat
      const res = await fetch(`${API}/api/videos`);
      const data = await res.json();
      setSeats(data.seats || []);
    } catch {
      // Error is already in veo.error
    }
  }, [selectedSection, veo]);

  const handleUploaded = useCallback((data) => {
    setSeats(prev => {
      const without = prev.filter(s => s.seatId !== data.seatId);
      return [...without, { seatId: data.seatId, section: parseInt(data.seatId), row: 1, videoUrl: data.videoUrl, type: 'real' }];
    });
  }, []);

  const realCount = seats.filter(s => s.type === 'real').length;
  const aiCount = seats.filter(s => s.type === 'ai').length;

  return (
    <div className="app">
      <header className="header">
        <div className="logo">STADIUMVIEW</div>
        <div className="header-right">
          <div className="legend">
            <div className="legend-item">
              <div className="dot-legend" style={{ background: '#00D4FF' }} />
              <span>Real footage ({realCount})</span>
            </div>
            <div className="legend-item">
              <div className="dot-legend" style={{ background: '#FF6B35' }} />
              <span>AI generated ({aiCount})</span>
            </div>
          </div>
          <div className="sport-tag">BASKETBALL</div>
          <button className="upload-btn" onClick={() => setShowUpload(true)}>
            + Upload Video
          </button>
        </div>
      </header>

      <div className="main">
        <div className="map-panel">
          <SeatMap
            seats={seats}
            selectedSeatId={selectedSection ? String(selectedSection) : null}
            onSectionClick={handleSectionClick}
          />
        </div>

        <VideoPanel
          section={selectedSection}
          seat={selectedSeat}
          veo={veo}
          onGenerate={handleGenerate}
        />
      </div>

      {showUpload && (
        <UploadModal onClose={() => setShowUpload(false)} onUploaded={handleUploaded} />
      )}
    </div>
  );
}
