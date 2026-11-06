import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import zlib from 'node:zlib';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 8888);

const DIRS = {
  certs: path.join(__dirname, 'certs'),
  hosts: path.join(__dirname, 'certs', 'hosts'),
  captured: path.join(__dirname, 'captured'),
  inject: path.join(__dirname, 'inject'),
};

for (const dir of Object.values(DIRS)) {
  fs.mkdirSync(dir, { recursive: true });
}

// Bypass Apple system domains that enforce strict OS-level SSL pinning
const PASSTHROUGH_SUFFIXES = [
  '.apple.com',
  '.icloud.com',
  '.mzstatic.com',
  '.cdn-apple.com',
  '.itunes.com',
  'apple.com',
  'icloud.com',
];

function shouldPassthrough(hostname) {
  const h = hostname.toLowerCase();
  return PASSTHROUGH_SUFFIXES.some((s) => h === s || h.endsWith(s));
}

const caKeyPath = path.join(DIRS.certs, 'ca.key');
const caCertPath = path.join(DIRS.certs, 'ca.crt');

function ensureRootCA() {
  if (fs.existsSync(caKeyPath) && fs.existsSync(caCertPath)) {
    return;
  }
  console.log('[CA] Generating local Root CA for iOS...');
  const cnfPath = path.join(DIRS.certs, 'ca.cnf');
  fs.writeFileSync(
    cnfPath,
    [
      '[ req ]',
      'default_bits = 2048',
      'prompt = no',
      'default_md = sha256',
      'distinguished_name = dn',
      'x509_extensions = v3_ca',
      '',
      '[ dn ]',
      'C = ID',
      'O = Aolon GTS3 Watchface Lab',
      'CN = Aolon GTS3 Watchface Proxy CA',
      '',
      '[ v3_ca ]',
      'subjectKeyIdentifier = hash',
      'authorityKeyIdentifier = keyid:always,issuer',
      'basicConstraints = critical, CA:true',
      'keyUsage = critical, digitalSignature, cRLSign, keyCertSign',
      '',
    ].join('\n')
  );

  execFileSync('openssl', [
    'req',
    '-x509',
    '-new',
    '-nodes',
    '-newkey',
    'rsa:2048',
    '-keyout',
    caKeyPath,
    '-sha256',
    '-days',
    '825',
    '-out',
    caCertPath,
    '-config',
    cnfPath,
  ]);
  console.log('[CA] Root CA ready:', caCertPath);
}

const certCache = new Map();

function getHostCredentials(hostname) {
  if (certCache.has(hostname)) {
    return certCache.get(hostname);
  }

  const safeName = hostname.replace(/[^a-zA-Z0-9._-]/g, '_');
  const keyFile = path.join(DIRS.hosts, `${safeName}.key`);
  const certFile = path.join(DIRS.hosts, `${safeName}.crt`);

  if (!fs.existsSync(keyFile) || !fs.existsSync(certFile)) {
    const csrFile = path.join(DIRS.hosts, `${safeName}.csr`);
    const extFile = path.join(DIRS.hosts, `${safeName}.ext`);
    const isIP = net.isIP(hostname) !== 0;
    const san = isIP ? `IP:${hostname}` : `DNS:${hostname}`;

    execFileSync('openssl', [
      'req',
      '-new',
      '-nodes',
      '-newkey',
      'rsa:2048',
      '-keyout',
      keyFile,
      '-subj',
      `/C=ID/O=Aolon GTS3 Lab/CN=${hostname}`,
      '-out',
      csrFile,
    ]);

    fs.writeFileSync(
      extFile,
      [
        'authorityKeyIdentifier=keyid,issuer',
        'basicConstraints=CA:FALSE',
        'keyUsage = digitalSignature, keyEncipherment',
        'extendedKeyUsage = serverAuth',
        `subjectAltName = ${san}`,
        '',
      ].join('\n')
    );

    execFileSync('openssl', [
      'x509',
      '-req',
      '-in',
      csrFile,
      '-CA',
      caCertPath,
      '-CAkey',
      caKeyPath,
      '-CAcreateserial',
      '-out',
      certFile,
      '-days',
      '365',
      '-sha256',
      '-extfile',
      extFile,
    ]);

    try {
      fs.unlinkSync(csrFile);
      fs.unlinkSync(extFile);
    } catch {}
  }

  const creds = tls.createSecureContext({
    key: fs.readFileSync(keyFile),
    cert: fs.readFileSync(certFile),
    ca: fs.readFileSync(caCertPath),
  });
  certCache.set(hostname, creds);
  return creds;
}

function servePortal(req, res) {
  const urlObj = new URL(req.url, 'http://wf.local');
  if (urlObj.pathname === '/ca.crt' || urlObj.pathname === '/cert') {
    const certData = fs.readFileSync(caCertPath);
    res.writeHead(200, {
      'Content-Type': 'application/x-x509-ca-cert',
      'Content-Disposition': 'attachment; filename="aolon-watchface-ca.crt"',
      'Content-Length': certData.length,
    });
    res.end(certData);
    console.log('[PORTAL] iPhone downloaded Root CA profile (/cert)');
    return;
  }

  const capturedFiles = fs
    .readdirSync(DIRS.captured)
    .filter((f) => !f.startsWith('.'))
    .sort()
    .reverse();
  const customBinPath = path.join(DIRS.inject, 'custom.bin');
  const injectReady = fs.existsSync(customBinPath);

  const html = `<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Aolon GTS3 Watchface Proxy</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 24px; max-width: 540px; margin: 0 auto; background: #0f172a; color: #f8fafc; }
    .card { background: #1e293b; border-radius: 16px; padding: 20px; margin-bottom: 16px; border: 1px solid #334155; }
    h1 { font-size: 20px; margin-top: 0; }
    .btn { display: block; text-align: center; background: #38bdf8; color: #0f172a; font-weight: 700; text-decoration: none; padding: 14px 18px; border-radius: 12px; margin: 16px 0; }
    ol { padding-left: 20px; line-height: 1.6; color: #cbd5e1; font-size: 14px; }
    code { background: #0f172a; padding: 2px 6px; border-radius: 6px; color: #38bdf8; }
    .badge { display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
    .ok { background: #065f46; color: #6ee7b7; }
    .wait { background: #3730a3; color: #c7d2fe; }
  </style>
</head>
<body>
  <div class="card">
    <h1>⌚ Aolon GTS3 Watchface Lab</h1>
    <p>Proxy koneksi berhasil! Ikuti 3 langkah cepat di iPhone:</p>
    <a class="btn" href="/cert">1. Download Sertifikat Proxy (iOS)</a>
    <ol>
      <li>Tap tombol biru di atas lalu pilih <b>Allow (Izinkan)</b>.</li>
      <li>Buka <b>Settings &gt; General &gt; VPN &amp; Device Management</b>, pilih profil <b>Aolon GTS3 Watchface Proxy CA</b>, lalu tap <b>Install</b>.</li>
      <li>Buka <b>Settings &gt; General &gt; About &gt; Certificate Trust Settings</b> (paling bawah), lalu <b>aktifkan switch</b> pada <b>Aolon GTS3 Watchface Proxy CA</b>.</li>
    </ol>
  </div>
  <div class="card">
    <p>Mode Injeksi Custom Watchface:
      <span class="badge ${injectReady ? 'ok' : 'wait'}">
        ${injectReady ? 'AKTIF (inject/custom.bin siap)' : 'STANDBY (Mode Capture Sampel .bin)'}
      </span>
    </p>
    <p style="font-size:13px;color:#94a3b8;">File tertangkap (${capturedFiles.length}): ${capturedFiles.slice(0, 5).join(', ') || 'Belum ada'}</p>
  </div>
</body>
</html>`;

  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(html);
}

function isInterestingWatchfaceUrl(urlStr, contentType = '') {
  const lower = urlStr.toLowerCase();
  if (
    lower.endsWith('.bin') ||
    lower.includes('.bin?') ||
    lower.endsWith('.dial') ||
    lower.includes('ute-tech.com') ||
    lower.includes('watch') ||
    lower.includes('clock') ||
    lower.includes('dial')
  ) {
    return true;
  }
  if (contentType.includes('application/octet-stream') && (lower.includes('oss') || lower.includes('file') || lower.includes('res'))) {
    return true;
  }
  return false;
}

function isBinaryWatchfaceDownload(urlStr, contentType = '', bodyBuf = Buffer.alloc(0)) {
  const lower = urlStr.toLowerCase();
  if (lower.endsWith('.bin') || lower.includes('.bin?')) return true;
  if (
    bodyBuf.length > 4096 &&
    (contentType.includes('octet-stream') || contentType.includes('binary')) &&
    (lower.includes('dial') || lower.includes('watch') || lower.includes('face') || lower.includes('clock') || lower.includes('oss'))
  ) {
    return true;
  }
  return false;
}

function saveCapturedArtifact(kind, fullUrl, bodyBuf, headers) {
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  const parsed = new URL(fullUrl);
  const base = path.basename(parsed.pathname) || 'payload';
  const safeBase = base.replace(/[^a-zA-Z0-9._-]/g, '_');
  const outName = `${ts}_${kind}_${safeBase}`;
  const outPath = path.join(DIRS.captured, outName);
  fs.writeFileSync(outPath, bodyBuf);

  const metaPath = `${outPath}.meta.json`;
  fs.writeFileSync(
    metaPath,
    JSON.stringify(
      {
        capturedAt: new Date().toISOString(),
        url: fullUrl,
        size: bodyBuf.length,
        md5: crypto.createHash('md5').update(bodyBuf).digest('hex'),
        sha256: crypto.createHash('sha256').update(bodyBuf).digest('hex'),
        headers,
      },
      null,
      2
    )
  );
  console.log(`\n🎯 [CAPTURED ${kind.toUpperCase()}] ${fullUrl}`);
  console.log(`   -> Saved to: ${outPath} (${bodyBuf.length} bytes)\n`);
}

function forwardHttpRequest(clientReq, clientRes, isTls, defaultHost) {
  let targetUrl;
  try {
    if (clientReq.url.startsWith('http://') || clientReq.url.startsWith('https://')) {
      targetUrl = new URL(clientReq.url);
    } else {
      const hostHeader = clientReq.headers.host || defaultHost;
      if (!hostHeader || hostHeader.startsWith('wf.local') || hostHeader.endsWith(`:${PORT}`)) {
        return servePortal(clientReq, clientRes);
      }
      targetUrl = new URL(clientReq.url, `${isTls ? 'https' : 'http'}://${hostHeader}`);
    }
  } catch {
    return servePortal(clientReq, clientRes);
  }

  if (targetUrl.hostname === 'wf.local') {
    return servePortal(clientReq, clientRes);
  }

  const fullUrl = targetUrl.toString();
  const customBinPath = path.join(DIRS.inject, 'custom.bin');
  const shouldInject =
    fs.existsSync(customBinPath) &&
    (targetUrl.pathname.toLowerCase().endsWith('.bin') || fullUrl.toLowerCase().includes('.bin?'));

  const outHeaders = { ...clientReq.headers };
  delete outHeaders['proxy-connection'];

  // Force uncompressed & non-partial response on interesting URLs so we get clean .bin / JSON
  if (isInterestingWatchfaceUrl(fullUrl) || outHeaders.accept?.includes('json')) {
    delete outHeaders['accept-encoding'];
    delete outHeaders['range'];
    delete outHeaders['if-none-match'];
    delete outHeaders['if-modified-since'];
  }

  console.log(`[${isTls ? 'HTTPS' : 'HTTP '}] ${clientReq.method} ${targetUrl.host}${targetUrl.pathname}`);

  if (shouldInject && clientReq.method === 'GET') {
    // Fetch first 64 bytes of target upstream .bin to adopt its exact Watchface ID & BCD ID!
    const headTransport = targetUrl.protocol === 'https:' ? https : http;
    const headReq = headTransport.request(
      {
        protocol: targetUrl.protocol,
        hostname: targetUrl.hostname,
        port: targetUrl.port || (targetUrl.protocol === 'https:' ? 443 : 80),
        method: 'GET',
        path: targetUrl.pathname + targetUrl.search,
        headers: { Host: targetUrl.host, Range: 'bytes=0-63' },
        rejectUnauthorized: false,
      },
      (headRes) => {
        const hChunks = [];
        headRes.on('data', (c) => hChunks.push(c));
        headRes.on('end', () => {
          const origHdr = Buffer.concat(hChunks);
          const customBuf = Buffer.from(fs.readFileSync(customBinPath));

          if (origHdr.length >= 32 && origHdr[0x18] === 0x57 && origHdr[0x19] === 0x46) {
            // Copy original wf_id (0..4) and WF+BCD header (0x18..0x20)
            origHdr.copy(customBuf, 0, 0, 4);
            origHdr.copy(customBuf, 0x18, 0x18, 0x20);
            const newCrc = zlib.crc32(customBuf.subarray(24)) >>> 0;
            customBuf.writeUInt32LE(newCrc, 8);
            const adoptedId = customBuf.readUInt32LE(0);
            console.log(
              `\n🚀 [INJECTED CUSTOM.BIN] Adopted Watchface ID=${adoptedId}, CRC32=0x${newCrc.toString(16)} (${customBuf.length} bytes) -> ${fullUrl}\n`
            );
          } else {
            console.log(`\n🚀 [INJECTED CUSTOM.BIN] Serving static ID (${customBuf.length} bytes) -> ${fullUrl}\n`);
          }

          const md5Hex = crypto.createHash('md5').update(customBuf).digest('hex');
          const md5B64 = crypto.createHash('md5').update(customBuf).digest('base64');
          clientRes.writeHead(200, {
            'Content-Type': 'application/octet-stream',
            'Content-Length': customBuf.length,
            'Content-MD5': md5B64,
            'Cache-Control': 'no-store',
            ETag: `"${md5Hex.toUpperCase()}"`,
          });
          clientRes.end(customBuf);
        });
      }
    );
    headReq.on('error', () => {
      const customBuf = fs.readFileSync(customBinPath);
      console.log(`\n🚀 [INJECTED CUSTOM.BIN FALLBACK] (${customBuf.length} bytes) -> ${fullUrl}\n`);
      clientRes.writeHead(200, {
        'Content-Type': 'application/octet-stream',
        'Content-Length': customBuf.length,
        'Cache-Control': 'no-store',
      });
      clientRes.end(customBuf);
    });
    headReq.end();
    return;
  }

  const transport = targetUrl.protocol === 'https:' ? https : http;
  const options = {
    protocol: targetUrl.protocol,
    hostname: targetUrl.hostname,
    port: targetUrl.port || (targetUrl.protocol === 'https:' ? 443 : 80),
    method: clientReq.method,
    path: targetUrl.pathname + targetUrl.search,
    headers: outHeaders,
    rejectUnauthorized: false,
  };

  const upstreamReq = transport.request(options, (upstreamRes) => {
    const ctype = (upstreamRes.headers['content-type'] || '').toLowerCase();
    const chunks = [];

    upstreamRes.on('data', (chunk) => chunks.push(chunk));
    upstreamRes.on('end', () => {
      const bodyBuf = Buffer.concat(chunks);

      if (isBinaryWatchfaceDownload(fullUrl, ctype, bodyBuf)) {
        saveCapturedArtifact('bin', fullUrl, bodyBuf, upstreamRes.headers);
      } else if (ctype.includes('json') || bodyBuf.slice(0, 1).toString() === '{') {
        const text = bodyBuf.toString('utf8');
        if (
          text.includes('.bin') ||
          text.toLowerCase().includes('dial') ||
          text.toLowerCase().includes('watch') ||
          text.toLowerCase().includes('clock') ||
          isInterestingWatchfaceUrl(fullUrl, ctype)
        ) {
          saveCapturedArtifact('json', fullUrl, bodyBuf, upstreamRes.headers);
        }
      }

      const resHeaders = { ...upstreamRes.headers };
      delete resHeaders['transfer-encoding'];
      resHeaders['content-length'] = bodyBuf.length;

      clientRes.writeHead(upstreamRes.statusCode || 200, resHeaders);
      clientRes.end(bodyBuf);
    });
  });

  upstreamReq.on('error', (err) => {
    console.error(`[UPSTREAM ERR] ${fullUrl}: ${err.message}`);
    if (!clientRes.headersSent) {
      clientRes.writeHead(502, { 'Content-Type': 'text/plain' });
    }
    clientRes.end(`Proxy upstream error: ${err.message}`);
  });

  clientReq.pipe(upstreamReq);
}

ensureRootCA();

// Internal HTTPS server handling decrypted CONNECT streams
const internalHttpsServer = https.createServer(
  {
    SNICallback: (servername, cb) => {
      try {
        cb(null, getHostCredentials(servername));
      } catch (err) {
        cb(err);
      }
    },
  },
  (req, res) => {
    forwardHttpRequest(req, res, true, req.socket.servername);
  }
);

const proxyServer = http.createServer((req, res) => {
  // Direct access to http://<MAC_IP>:8888 or http://wf.local
  if (!req.url.startsWith('http://')) {
    return servePortal(req, res);
  }
  forwardHttpRequest(req, res, false, req.headers.host);
});

proxyServer.on('connect', (req, clientSocket, head) => {
  const [hostname, portStr] = req.url.split(':');
  const targetPort = Number(portStr || 443);

  if (shouldPassthrough(hostname)) {
    const upstreamSocket = net.connect(targetPort, hostname, () => {
      clientSocket.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      if (head && head.length) upstreamSocket.write(head);
      upstreamSocket.pipe(clientSocket);
      clientSocket.pipe(upstreamSocket);
    });
    upstreamSocket.on('error', () => clientSocket.destroy());
    clientSocket.on('error', () => upstreamSocket.destroy());
    return;
  }

  // MITM TLS termination via internalHttpsServer
  clientSocket.write('HTTP/1.1 200 Connection Established\r\n\r\n');
  if (head && head.length) {
    clientSocket.unshift(head);
  }
  internalHttpsServer.emit('connection', clientSocket);
  clientSocket.on('error', (err) => {
    if (err.code !== 'ECONNRESET') {
      console.error(`[TLS CLIENT ERR] ${hostname}: ${err.message}`);
    }
  });
});

proxyServer.listen(PORT, '0.0.0.0', () => {
  console.log('====================================================');
  console.log(` Aolon GTS3 Watchface Proxy aktif di port ${PORT}`);
  console.log(` Portal Sertifikat iPhone: http://wf.local (via proxy)`);
  console.log('====================================================');
});
