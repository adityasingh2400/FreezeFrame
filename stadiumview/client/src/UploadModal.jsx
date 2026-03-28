import React, { useState } from 'react';

const API = import.meta.env.VITE_API_BASE || '';

export default function UploadModal({ onClose, onUploaded }) {
  const [section, setSection] = useState('');
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e) {
    e.preventDefault();
    if (!file || !section) { setError('Section and video file are required'); return; }
    setUploading(true);
    setError('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('seatId', String(section));
      fd.append('section', String(section));
      fd.append('row', '1');
      const res = await fetch(`${API}/api/upload`, { method: 'POST', body: fd });
      if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`);
      const data = await res.json();
      onUploaded(data);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2>Upload Fan Footage</h2>
        <form onSubmit={handleSubmit}>
          <label>SECTION NUMBER</label>
          <input
            type="number"
            placeholder="e.g. 101"
            value={section}
            onChange={e => setSection(e.target.value)}
            min="100"
            max="212"
          />
          <label>VIDEO FILE</label>
          <input
            type="file"
            accept="video/*"
            onChange={e => setFile(e.target.files[0])}
          />
          {error && <div style={{ color: '#EF4444', fontSize: 11, marginTop: 8 }}>{error}</div>}
          <div className="modal-actions">
            <button type="submit" className="btn-primary" disabled={uploading}>
              {uploading ? 'Uploading...' : 'Upload'}
            </button>
            <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          </div>
        </form>
      </div>
    </div>
  );
}
