import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import {readFileSync,existsSync,createReadStream} from 'node:fs';
import {resolve,extname,sep} from 'node:path';
import {fileURLToPath} from 'node:url';
const repo=resolve(fileURLToPath(new URL('../..',import.meta.url)));
// Preview the same packaged legacy screens alongside the mobile workspace.
// API requests retain the existing isolated QA proxy; no production sessions.
const legacyPreview={name:'connected-preview',configureServer(server:any){
  server.middlewares.use((req:any,res:any,next:any)=>{
    const pathname=new URL(req.url,'http://localhost').pathname;
    if(/^\/(territorio|v1|salud|@|node_modules|src)(\/|$)/.test(pathname))return next();
    const pointer=resolve(repo,'.cache/preview-web-path.txt');
    const base=existsSync(pointer)?readFileSync(pointer,'utf8').trim():resolve(repo,'deployments/vps-20261006/web');
    if(!base.startsWith(repo+sep))return next();
    const path=resolve(base,'.'+pathname);
    if(!path.startsWith(base+sep)&&path!==base)return next();
    const file=extname(path)?path:resolve(base,'index.html');
    if(!existsSync(file))return next();
    const type:Record<string,string>={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.json':'application/json','.woff2':'font/woff2','.png':'image/png','.webmanifest':'application/manifest+json'};
    res.setHeader('Content-Type',type[extname(file)]||'application/octet-stream');
    res.setHeader('Cache-Control','no-store');createReadStream(file).pipe(res);
  });
}};
export default defineConfig({
  base: "/territorio/",
  plugins: [react(),legacyPreview],
  server: {
    port: 4321,
    proxy: {
      "/v1": "http://127.0.0.1:8321",
      "/salud": "http://127.0.0.1:8321",
    },
  },
});
