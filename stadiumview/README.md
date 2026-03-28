# StadiumView

Multi-angle fan video map with Veo AI angle synthesis.

## Setup

```bash
# 1. Copy and fill in your Google AI Studio API key
cp .env.example .env
# Edit .env and set GOOGLE_API_KEY=...

# 2. Install server deps
cd server && npm install

# 3. Install client deps
cd ../client && npm install

# 4. Run both in separate terminals
# Terminal 1:
cd server && npm start

# Terminal 2:
cd client && npm run dev
```

Open http://localhost:5173

## Demo prep

Before the demo, pre-generate a few seats so they load instantly:

```bash
curl -X POST http://localhost:3001/api/generate \
  -H "Content-Type: application/json" \
  -d '{"seatId":"108","section":108,"row":5}'

# Wait ~60 seconds, then:
curl -X POST http://localhost:3001/api/generate \
  -H "Content-Type: application/json" \
  -d '{"seatId":"204","section":204,"row":10}'
```

Upload real footage:
```bash
curl -X POST http://localhost:3001/api/upload \
  -F "file=@your-video.mp4" \
  -F "seatId=101" \
  -F "section=101" \
  -F "row=3"
```
