const { GoogleGenAI } = require('@google/genai');

const ai = new GoogleGenAI({ apiKey: process.env.GOOGLE_API_KEY });

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function generateVideo(prompt) {
  let op = await ai.models.generateVideos({
    model: 'veo-002',
    prompt,
    config: { durationSeconds: 5, aspectRatio: '16:9' },
  });

  let attempts = 0;
  while (!op.done) {
    if (++attempts > 24) throw new Error('Veo generation timed out after 120s');
    await sleep(5000);
    op = await ai.operations.get({ name: op.name });
  }

  const video = op.response.generatedVideos[0];
  if (!video) throw new Error('Veo returned no video');
  return video.video.uri;
}

module.exports = { generateVideo };
