import React from 'react';

const API = import.meta.env.VITE_API_BASE || '';

export default function VideoPanel({ section, seat, veo, onGenerate }) {
  const hasVideo = seat?.videoUrl || veo.status === 'done';
  const videoUrl = veo.status === 'done' ? veo.videoUrl : seat?.videoUrl;
  const isGenerating = veo.status === 'generating';
  const isFailed = veo.status === 'failed';

  // Compute angle description for display
  const angleMap = {
    '0-10':  'South baseline',
    '11-20': 'East sideline',
    '21-30': 'North baseline',
    '31-40': 'West sideline',
  };
  const s = section ? section % 100 : 0;
  let angle = 'West sideline';
  if (s <= 10) angle = 'South baseline';
  else if (s <= 20) angle = 'East sideline';
  else if (s <= 30) angle = 'North baseline';

  const deck = section >= 200 ? 'Upper deck' : 'Lower bowl';
  const statusLabel = seat?.type === 'real' ? 'Real footage' : seat?.type === 'ai' ? 'AI generated' : 'No footage';
  const statusClass = seat?.type === 'real' ? 'cyan' : seat?.type === 'ai' ? 'orange' : '';

  if (!section) {
    return (
      <div className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-title" style={{ color: 'var(--text-muted)' }}>No seat selected</div>
          <div className="sidebar-subtitle">Click any section on the map</div>
        </div>
        <div className="video-area">
          <div className="video-placeholder">
            <div className="play-icon">&#9654;</div>
            Select a section
          </div>
        </div>
        <div className="status-bar">
          <span>Click a section to view or generate</span>
        </div>
      </div>
    );
  }

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-title">Section {section}</div>
        <div className="sidebar-subtitle">{deck} &middot; {angle}</div>
      </div>

      <div className="video-area">
        {hasVideo ? (
          <video
            key={videoUrl}
            src={API + videoUrl}
            autoPlay
            loop
            muted
            controls
            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          />
        ) : (
          <div className="video-placeholder">
            <div className="play-icon">&#9654;</div>
            {isFailed ? 'Generation failed' : 'No footage yet'}
          </div>
        )}
      </div>

      <div className="seat-info">
        <div className="info-row">
          <span className="info-label">SECTION</span>
          <span className="info-value">{section}</span>
        </div>
        <div className="info-row">
          <span className="info-label">DECK</span>
          <span className="info-value">{deck}</span>
        </div>
        <div className="info-row">
          <span className="info-label">ANGLE</span>
          <span className="info-value">{angle}</span>
        </div>
        <div className="info-row">
          <span className="info-label">STATUS</span>
          <span className={`info-value ${statusClass}`}>{statusLabel}</span>
        </div>
      </div>

      {isGenerating && (
        <div className="loading-state">
          <div className="loading-label">VEO GENERATING &middot; ~60s</div>
          <div className="loading-bar"><div className="loading-fill" /></div>
          <div className="loading-text">Synthesizing view from Section {section}...</div>
        </div>
      )}

      {isFailed && (
        <div className="loading-state" style={{ borderColor: 'rgba(239,68,68,0.3)', background: 'rgba(239,68,68,0.08)' }}>
          <div className="loading-label" style={{ color: '#EF4444' }}>GENERATION FAILED</div>
          <div className="loading-text" style={{ color: '#EF4444' }}>{veo.error}</div>
        </div>
      )}

      {!isGenerating && !hasVideo && (
        <button className="generate-btn" onClick={onGenerate} disabled={isGenerating}>
          &#9889; Generate with Veo
        </button>
      )}

      {hasVideo && seat?.type !== 'real' && (
        <button className="generate-btn" onClick={onGenerate} disabled={isGenerating}>
          &#8635; Regenerate with Veo
        </button>
      )}

      <div className="status-bar">
        <span>Sec {section} &middot; {seat?.type === 'real' ? 'Fan upload' : seat?.type === 'ai' ? 'Veo AI' : 'Empty'}</span>
        <span style={{ color: 'var(--cyan)' }}>Veo-002</span>
      </div>
    </div>
  );
}
