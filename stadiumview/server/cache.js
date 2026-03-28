const fs = require('fs');
const path = require('path');

const CACHE_DIR = path.join(__dirname, '../cache');
const INDEX_PATH = path.join(CACHE_DIR, 'index.json');

function loadIndex() {
  if (!fs.existsSync(INDEX_PATH)) return {};
  return JSON.parse(fs.readFileSync(INDEX_PATH, 'utf8'));
}

function saveIndex(index) {
  fs.writeFileSync(INDEX_PATH, JSON.stringify(index, null, 2));
}

function get(seatId) {
  return loadIndex()[seatId] || null;
}

function set(seatId, entry) {
  const index = loadIndex();
  index[seatId] = entry;
  saveIndex(index);
}

function all() {
  return loadIndex();
}

function uploadsDir() {
  return path.join(CACHE_DIR, 'uploads');
}

module.exports = { get, set, all, uploadsDir, CACHE_DIR };
