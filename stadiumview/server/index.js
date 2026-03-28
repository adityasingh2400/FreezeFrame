require('dotenv').config({ path: require('path').join(__dirname, '../.env') });
const express = require('express');
const cors = require('cors');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const { v4: uuidv4 } = require('uuid');
const { generateVideo } = require('./veoClient');
const { buildVeoPrompt } = require('./promptBuilder');
const cache = require('./cache');

const app = express();
app.use(cors());
app.use(express.json());

// Serve cached videos as static files
app.use('/cache', express.static(path.join(__dirname, '../cache')));

// In-memory job tracker
const jobs = {};

// ── POST /api/generate ────────────────────────────────────────────────────────
// Body: { seatId, section, row, sport? }
// Returns: { jobId, status: 'generating' } or { videoUrl, status: 'cached' }
app.post('/api/generate', async (req, res) => {
  const { seatId, section, row, sport = 'basketball' } = req.body;
  if (!seatId || section == null || row == null) {
    return res.status(400).json({ error: 'seatId, section, and row are required' });
  }

  // Return immediately if already cached
  const cached = cache.get(seatId);
  if (cached && cached.type === 'ai' && cached.videoUrl) {
    return res.json({ status: 'cached', videoUrl: cached.videoUrl });
  }

  const jobId = uuidv4();
  jobs[jobId] = { status: 'generating', seatId, section, row };
  res.json({ jobId, status: 'generating', estimatedSeconds: 60 });

  // Run generation in background
  const prompt = buildVeoPrompt(Number(section), Number(row), sport);
  generateVideo(prompt)
    .then(async (uri) => {
      // Veo returns a gs:// URI — fetch and save locally
      const ext = '.mp4';
      const filename = `ai-${seatId}${ext}`;
      const localPath = path.join(cache.CACHE_DIR, filename);

      // Download from Google storage
      const https = require('https');
      const http = require('http');
      const url = require('url');
      const parsed = url.parse(uri);
      const client = parsed.protocol === 'https:' ? https : http;

      await new Promise((resolve, reject) => {
        client.get(uri, (response) => {
          const out = fs.createWriteStream(localPath);
          response.pipe(out);
          out.on('finish', resolve);
          out.on('error', reject);
        }).on('error', reject);
      });

      const videoUrl = `/cache/${filename}`;
      jobs[jobId] = { status: 'done', videoUrl };
      cache.set(seatId, { seatId, section, row, videoUrl, type: 'ai' });
    })
    .catch((err) => {
      console.error(`Veo generation failed for ${seatId}:`, err.message);
      jobs[jobId] = { status: 'failed', error: err.message };
    });
});

// ── GET /api/status/:jobId ────────────────────────────────────────────────────
// Returns: { status, videoUrl?, error?, estimatedSeconds? }
app.get('/api/status/:jobId', (req, res) => {
  const job = jobs[req.params.jobId];
  if (!job) return res.status(404).json({ error: 'Job not found' });
  res.json(job);
});

// ── POST /api/upload ──────────────────────────────────────────────────────────
// Multipart: file + seatId + section + row
// Returns: { seatId, videoUrl }
const upload = multer({ dest: cache.uploadsDir() });
app.post('/api/upload', upload.single('file'), (req, res) => {
  const { seatId, section, row } = req.body;
  if (!seatId || !req.file) {
    return res.status(400).json({ error: 'seatId and file are required' });
  }

  const ext = path.extname(req.file.originalname) || '.mp4';
  const filename = `real-${seatId}${ext}`;
  const destPath = path.join(cache.uploadsDir(), filename);
  fs.renameSync(req.file.path, destPath);

  const videoUrl = `/cache/uploads/${filename}`;
  cache.set(seatId, {
    seatId,
    section: Number(section),
    row: Number(row),
    videoUrl,
    type: 'real',
  });

  res.json({ seatId, videoUrl });
});

// ── GET /api/videos ───────────────────────────────────────────────────────────
// Returns all seats with video (real + AI generated)
app.get('/api/videos', (req, res) => {
  const all = cache.all();
  res.json({ seats: Object.values(all) });
});

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => console.log(`StadiumView server running on http://localhost:${PORT}`));
