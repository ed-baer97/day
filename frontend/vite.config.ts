import http from "node:http";
import { defineConfig, type ViteDevServer } from "vite";
import react from "@vitejs/plugin-react";

const LOCAL_API = "http://127.0.0.1:8000";
const LIVE_LEVELS = "http://93.171.232.47/api/v1/public/levels";

type LevelStation = {
  code: string;
  name?: string;
  address?: string;
  tanks?: unknown[];
};

function getJson(url: string, timeoutMs: number): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      const chunks: Buffer[] = [];
      res.on("data", (chunk: Buffer) => chunks.push(chunk));
      res.on("end", () => {
        if ((res.statusCode ?? 500) >= 400) {
          reject(new Error(String(res.statusCode)));
          return;
        }
        try {
          resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
        } catch (error) {
          reject(error);
        }
      });
    });
    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy(new Error("timeout"));
    });
  });
}

function withLiveReading(local: LevelStation[], live: LevelStation[]): LevelStation[] {
  const byCode = new Map(live.map((station) => [station.code, station]));
  return local.map((station) => {
    const remote = byCode.get(station.code);
    if (!remote?.tanks?.length) return station;
    return {
      ...station,
      name: remote.name || station.name,
      address: remote.address || station.address,
      tanks: remote.tanks,
    };
  });
}

function liveLevelsPlugin() {
  return {
    name: "live-levels-on-site",
    configureServer(server: ViteDevServer) {
      server.middlewares.use((req, res, next) => {
        const path = (req.url ?? "").split("?")[0];
        if (path !== "/api/v1/public/levels") {
          next();
          return;
        }
        void (async () => {
          try {
            const local = (await getJson(`${LOCAL_API}/api/v1/public/levels`, 4000)) as LevelStation[];
            let live: LevelStation[] = [];
            try {
              live = (await getJson(LIVE_LEVELS, 4000)) as LevelStation[];
            } catch {
              live = [];
            }
            const body = JSON.stringify(
              withLiveReading(Array.isArray(local) ? local : [], Array.isArray(live) ? live : [])
            );
            res.setHeader("Content-Type", "application/json; charset=utf-8");
            res.end(body);
          } catch {
            next();
          }
        })();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), liveLevelsPlugin()],
  server: {
    host: true,
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": LOCAL_API,
      "/health": LOCAL_API,
    },
  },
});
