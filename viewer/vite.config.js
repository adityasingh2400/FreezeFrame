import { defineConfig, loadEnv } from 'vite';
import path from 'path';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, path.resolve(__dirname, '..'), '');
  const agentId = env.ELEVENLABS_AGENT_ID;
  const apiKey  = env.ELEVENLABS_API_KEY;

  return {
    server: {
      port: 5173,
      open: true,
      fs: {
        allow: [path.resolve(__dirname, '..')],
      },
      proxy: {
        '/api/signed-url': {
          target: `https://api.elevenlabs.io/v1/convai/conversation/get_signed_url?agent_id=${agentId}`,
          changeOrigin: true,
          rewrite: () => '',
          configure: (proxy) => {
            proxy.on('proxyReq', (proxyReq) => {
              proxyReq.setHeader('xi-api-key', apiKey);
            });
          },
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: true,
    },
  };
});
