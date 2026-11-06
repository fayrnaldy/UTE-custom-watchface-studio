import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function getLocalWifiIp() {
  const nets = os.networkInterfaces();
  for (const name of ['en0', 'en1', ...Object.keys(nets)]) {
    for (const net of nets[name] || []) {
      if (net.family === 'IPv4' && !net.internal) {
        return net.address;
      }
    }
  }
  return '127.0.0.1';
}

const ip = getLocalWifiIp();
console.log('==========================================================');
console.log(' ⌚ AOLON GTS3 WATCHFACE LAB — STUDIO + PROXY LAUNCHER');
console.log('==========================================================');
console.log(` 🎨 Web Studio (Buka di Mac) : http://localhost:3333`);
console.log(` 📡 IP Proxy iPhone Saat Ini : ${ip}  |  Port: 8888`);
console.log('    (Tekan Ctrl + C kapan saja untuk mematikan keduanya)');
console.log('==========================================================\n');

const studioProc = spawn(process.execPath, [path.join(__dirname, 'studio.mjs')], { stdio: 'inherit' });
const proxyProc = spawn(process.execPath, [path.join(__dirname, 'proxy.mjs')], { stdio: 'inherit' });

function shutdown() {
  console.log('\nMematikan Studio & Proxy...');
  studioProc.kill('SIGTERM');
  proxyProc.kill('SIGTERM');
  process.exit(0);
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
