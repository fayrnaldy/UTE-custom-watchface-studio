import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.STUDIO_PORT || 3333);

const DIRS = {
  inject: path.join(__dirname, 'inject'),
  projects: path.join(__dirname, 'projects'),
  previews: path.join(__dirname, 'previews'),
  unpacked: path.join(__dirname, 'unpacked'),
  assets: path.join(__dirname, 'assets'),
};

for (const d of Object.values(DIRS)) {
  fs.mkdirSync(d, { recursive: true });
}

function rgb888ToRgb565Parts(r8, g8, b8) {
  const r5 = (r8 >> 3) & 0x1f;
  const g6 = (g8 >> 2) & 0x3f;
  const b5 = (b8 >> 3) & 0x1f;
  const c = (r5 << 11) | (g6 << 5) | b5;
  return { r5, g6, b5, c };
}

/**
 * Encode an RGBA8888 Uint8Array/Buffer into UTE 'PA' (fmt 0x0200) compressed asset Buffer.
 * Bit-accurate match with ute_wf.py encode_pa.
 */
export function encodePA(width, height, rgba) {
  const encodedRows = [];
  const stride = width * 4;

  for (let y = 0; y < height; y++) {
    const rowOff = y * stride;
    const pixels = new Array(width);
    for (let x = 0; x < width; x++) {
      const p = rowOff + x * 4;
      const a8 = rgba[p + 3];
      if (a8 === 0) {
        pixels[x] = { a: 0, r5: 0, g6: 0, b5: 0, c: 0 };
      } else {
        const { r5, g6, b5, c } = rgb888ToRgb565Parts(rgba[p], rgba[p + 1], rgba[p + 2]);
        pixels[x] = { a: a8, r5, g6, b5, c };
      }
    }

    const lineBytes = [];
    let pa = 0, pr5 = 0, pg6 = 0, pb5 = 0;
    let x = 0;

    while (x < width) {
      const { a, r5, g6, b5, c } = pixels[x];
      let run = 1;
      while (x + run < width && run < 63) {
        const nxt = pixels[x + run];
        if (nxt.a === a && nxt.c === c) {
          run++;
        } else {
          break;
        }
      }

      if (run >= 2) {
        if (run <= 3 && a === pa && r5 === pr5 && g6 === pg6 && b5 === pb5) {
          for (let k = 0; k < run; k++) lineBytes.push(0x52);
        } else {
          lineBytes.push(0x80 | run, a, c & 0xff, (c >> 8) & 0xff);
          pa = a; pr5 = r5; pg6 = g6; pb5 = b5;
        }
        x += run;
        continue;
      }

      if (a === pa) {
        const dr = ((r5 - pr5 + 16) % 32 + 32) % 32 - 16;
        const dg = ((g6 - pg6 + 32) % 64 + 64) % 64 - 32;
        const db = ((b5 - pb5 + 16) % 32 + 32) % 32 - 16;
        if (dr >= -2 && dr <= 1 && dg >= -4 && dg <= 3 && db >= -2 && db <= 1) {
          const op = ((dr + 2) << 5) | ((dg + 4) << 2) | (db + 2);
          lineBytes.push(op);
          pr5 = r5; pg6 = g6; pb5 = b5;
          x += 1;
          continue;
        }

        const lit = [c];
        let tr5 = r5, tg6 = g6, tb5 = b5;
        while (x + lit.length < width && lit.length < 63) {
          const np = pixels[x + lit.length];
          if (np.a !== a) break;
          if (x + lit.length + 1 < width) {
            const np2 = pixels[x + lit.length + 1];
            if (np2.a === np.a && np2.c === np.c) break;
          }
          const ndr = ((np.r5 - tr5 + 16) % 32 + 32) % 32 - 16;
          const ndg = ((np.g6 - tg6 + 32) % 64 + 64) % 64 - 32;
          const ndb = ((np.b5 - tb5 + 16) % 32 + 32) % 32 - 16;
          if (ndr >= -2 && ndr <= 1 && ndg >= -4 && ndg <= 3 && ndb >= -2 && ndb <= 1) {
            break;
          }
          lit.push(np.c);
          tr5 = np.r5; tg6 = np.g6; tb5 = np.b5;
        }

        lineBytes.push(0xc0 | lit.length);
        for (const lc of lit) {
          lineBytes.push(lc & 0xff, (lc >> 8) & 0xff);
        }
        pa = a; pr5 = tr5; pg6 = tg6; pb5 = tb5;
        x += lit.length;
        continue;
      }

      lineBytes.push(0x81, a, c & 0xff, (c >> 8) & 0xff);
      pa = a; pr5 = r5; pg6 = g6; pb5 = b5;
      x += 1;
    }

    encodedRows.push(Buffer.from(lineBytes));
  }

  const cum = [0];
  for (const rb of encodedRows) {
    cum.push(cum[cum.length - 1] + rb.length);
  }
  const totalData = cum[cum.length - 1];
  const extra = Math.round(totalData / Math.max(1, height));

  const tblBuf = Buffer.alloc((height + 1) * 2);
  for (let r = 0; r <= height; r++) {
    const delta = cum[r] - r * extra;
    if (delta < -32768 || delta > 32767) {
      throw new Error(`Row scanline delta overflow (${delta}) on ${width}x${height} asset`);
    }
    tblBuf.writeInt16LE(delta, r * 2);
  }

  const hdr = Buffer.alloc(16);
  hdr.write('PA', 0, 'ascii');
  hdr.writeUInt16LE(0x0100, 2);
  hdr.writeUInt16LE(width, 4);
  hdr.writeUInt16LE(height, 6);
  hdr.writeUInt16LE(0x0200, 8);
  hdr.writeUInt16LE(extra, 10);
  // bytes 12..15 = 0

  return Buffer.concat([hdr, tblBuf, ...encodedRows]);
}

export function packBin(wfId, wfBcdHex, width, height, widgetsSpec, encodedAssetsMap) {
  const count = widgetsSpec.length;
  const tableEndRel = 0x34 + count * 20;

  const assetOffsets = new Map();
  const assetBlobs = [];
  let curRel = tableEndRel;

  for (const w of widgetsSpec) {
    if (!assetOffsets.has(w.assetKey)) {
      const paBuf = encodedAssetsMap.get(w.assetKey);
      if (!paBuf) throw new Error(`Missing encoded asset for key: ${w.assetKey}`);
      assetOffsets.set(w.assetKey, curRel);
      assetBlobs.push(paBuf);
      curRel += paBuf.length;
    }
  }

  const payloadSize = curRel;
  const wfHdr = Buffer.alloc(40, 0);
  Buffer.from([0x57, 0x46, 0x0c, 0x04, 0x01]).copy(wfHdr, 0);
  Buffer.from(wfBcdHex, 'hex').copy(wfHdr, 5);

  const wfMeta = Buffer.alloc(12);
  wfMeta.writeUInt16LE(1, 0);
  wfMeta.writeUInt16LE(width, 2);
  wfMeta.writeUInt16LE(height, 4);
  wfMeta.writeUInt16LE(count, 6);
  wfMeta.writeUInt32LE(payloadSize, 8);

  const descBuf = Buffer.alloc(count * 20);
  widgetsSpec.forEach((w, idx) => {
    const base = idx * 20;
    descBuf.writeUInt32LE(assetOffsets.get(w.assetKey), base);
    const [t0, t1] = w.typeHex.trim().split(/\s+/).map((h) => parseInt(h, 16));
    descBuf[base + 4] = t0;
    descBuf[base + 5] = t1;
    descBuf[base + 6] = w.frames & 0xff;
    descBuf[base + 7] = w.align & 0xff;
    descBuf.writeUInt16LE(Math.max(0, Math.min(65535, Math.round(w.x))), base + 8);
    descBuf.writeUInt16LE(Math.max(0, Math.min(65535, Math.round(w.y))), base + 10);
    Buffer.from(w.tailHex, 'hex').copy(descBuf, base + 12);
  });

  const payload = Buffer.concat([wfHdr, wfMeta, descBuf, ...assetBlobs]);
  const crc = zlib.crc32(payload) >>> 0;

  const outer = Buffer.alloc(24, 0);
  outer.writeUInt32LE(wfId >>> 0, 0);
  outer.writeUInt32LE(payloadSize >>> 0, 4);
  outer.writeUInt32LE(crc, 8);
  outer.writeUInt16LE(width, 12);
  outer.writeUInt16LE(height, 14);
  Buffer.from([0x01, 0x01, 0x01, 0x02, 0x00, 0x00, 0x00, 0x00]).copy(outer, 16);

  return { binBuf: Buffer.concat([outer, payload]), crc, payloadSize };
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let len = 0;
    req.on('data', (c) => {
      len += c.length;
      if (len > 50 * 1024 * 1024) {
        reject(new Error('Payload too large'));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch (e) {
        reject(e);
      }
    });
    req.on('error', reject);
  });
}

function sendJson(res, code, obj) {
  const body = Buffer.from(JSON.stringify(obj));
  res.writeHead(code, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': body.length,
    'Cache-Control': 'no-store',
  });
  res.end(body);
}

const server = http.createServer(async (req, res) => {
  try {
    const urlObj = new URL(req.url, `http://127.0.0.1:${PORT}`);

    if (req.method === 'GET' && (urlObj.pathname === '/' || urlObj.pathname === '/index.html')) {
      const htmlPath = path.join(__dirname, 'studio.html');
      const html = fs.readFileSync(htmlPath);
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
      res.end(html);
      return;
    }

    if (req.method === 'GET' && urlObj.pathname === '/api/mask') {
      const maskPath = path.join(__dirname, 'stock_mask.png');
      const png = fs.readFileSync(maskPath);
      res.writeHead(200, { 'Content-Type': 'image/png', 'Cache-Control': 'max-age=3600' });
      res.end(png);
      return;
    }

    if (req.method === 'GET' && urlObj.pathname.startsWith('/api/assets/')) {
      const fname = path.basename(decodeURIComponent(urlObj.pathname.slice('/api/assets/'.length)));
      const fpath = path.join(DIRS.assets, fname);
      if (!fs.existsSync(fpath)) {
        sendJson(res, 404, { ok: false, error: 'Asset not found' });
        return;
      }
      const buf = fs.readFileSync(fpath);
      res.writeHead(200, { 'Content-Type': 'image/png', 'Cache-Control': 'no-cache' });
      res.end(buf);
      return;
    }

    if (req.method === 'GET' && urlObj.pathname === '/api/status') {
      const customBin = path.join(DIRS.inject, 'custom.bin');
      let injectInfo = null;
      if (fs.existsSync(customBin)) {
        const st = fs.statSync(customBin);
        const buf = fs.readFileSync(customBin);
        const crc = buf.length >= 12 ? buf.readUInt32LE(8) : 0;
        injectInfo = {
          sizeBytes: st.size,
          sizeKB: +(st.size / 1024).toFixed(1),
          updatedAt: st.mtime.toISOString(),
          crcHex: '0x' + crc.toString(16).padStart(8, '0'),
        };
      }
      const projects = fs
        .readdirSync(DIRS.projects)
        .filter((f) => f.endsWith('.json'))
        .sort();
      sendJson(res, 200, { ok: true, inject: injectInfo, projects });
      return;
    }

    if (req.method === 'GET' && urlObj.pathname === '/api/download-bin') {
      const customBin = path.join(DIRS.inject, 'custom.bin');
      if (!fs.existsSync(customBin)) {
        sendJson(res, 404, { ok: false, error: 'Belum ada custom.bin yang di-compile.' });
        return;
      }
      const fname = (urlObj.searchParams.get('name') || 'aolon_gts3_custom').replace(/[^a-zA-Z0-9_-]/g, '_');
      const buf = fs.readFileSync(customBin);
      res.writeHead(200, {
        'Content-Type': 'application/octet-stream',
        'Content-Disposition': `attachment; filename="${fname}.bin"`,
        'Content-Length': buf.length,
      });
      res.end(buf);
      return;
    }

    if (req.method === 'POST' && urlObj.pathname === '/api/projects') {
      const body = await readJsonBody(req);
      const safeName = String(body.name || 'project')
        .trim()
        .replace(/[^a-zA-Z0-9_-]/g, '_')
        .slice(0, 64) || 'project';
      const outPath = path.join(DIRS.projects, `${safeName}.json`);
      fs.writeFileSync(outPath, JSON.stringify(body.project, null, 2));
      sendJson(res, 200, { ok: true, file: `${safeName}.json` });
      return;
    }

    if (req.method === 'GET' && urlObj.pathname.startsWith('/api/projects/')) {
      const rawName = decodeURIComponent(urlObj.pathname.slice('/api/projects/'.length));
      const safeName = path.basename(rawName);
      const pPath = path.join(DIRS.projects, safeName);
      if (!fs.existsSync(pPath)) {
        sendJson(res, 404, { ok: false, error: 'File proyek tidak ditemukan.' });
        return;
      }
      const project = JSON.parse(fs.readFileSync(pPath, 'utf8'));
      sendJson(res, 200, { ok: true, project });
      return;
    }

    if (req.method === 'POST' && urlObj.pathname === '/api/compile') {
      const t0 = Date.now();
      const body = await readJsonBody(req);
      const width = 390;
      const height = 450;

      const encodedMap = new Map();
      for (const [key, asset] of Object.entries(body.assets)) {
        const rgbaBuf = Buffer.from(asset.rgbaBase64, 'base64');
        if (rgbaBuf.length !== asset.width * asset.height * 4) {
          throw new Error(`Invalid RGBA buffer length for ${key}: got ${rgbaBuf.length}, expected ${asset.width * asset.height * 4}`);
        }
        encodedMap.set(key, encodePA(asset.width, asset.height, rgbaBuf));
      }

      const { binBuf, crc } = packBin(
        26950001,
        '009526',
        width,
        height,
        body.widgets,
        encodedMap
      );

      const customBinPath = path.join(DIRS.inject, 'custom.bin');
      fs.writeFileSync(customBinPath, binBuf);

      if (body.previewPngBase64) {
        const safeName = String(body.name || 'studio_watchface').replace(/[^a-zA-Z0-9_-]/g, '_');
        const pngData = Buffer.from(body.previewPngBase64.replace(/^data:image\/png;base64,/, ''), 'base64');
        fs.writeFileSync(path.join(DIRS.previews, `${safeName}.png`), pngData);
      }

      // Run strict Python round-trip unpack & CRC32 check via ute_wf.py!
      const verifyDir = path.join(DIRS.unpacked, 'studio_verify');
      execFileSync('python3', [
        '-c',
        `import sys; sys.path.insert(0, ${JSON.stringify(__dirname)}); from ute_wf import unpack_bin; m = unpack_bin(${JSON.stringify(customBinPath)}, ${JSON.stringify(verifyDir)}); assert m['crc_ok'], 'CRC mismatch'`,
      ]);

      const elapsedMs = Date.now() - t0;
      console.log(
        `[STUDIO COMPILE] Built inject/custom.bin (${(binBuf.length / 1024).toFixed(1)} KB, ${body.widgets.length} widgets, CRC=0x${crc.toString(16)}) in ${elapsedMs}ms`
      );

      sendJson(res, 200, {
        ok: true,
        sizeBytes: binBuf.length,
        sizeKB: +(binBuf.length / 1024).toFixed(1),
        crcHex: '0x' + crc.toString(16).padStart(8, '0'),
        widgetCount: body.widgets.length,
        elapsedMs,
      });
      return;
    }

    sendJson(res, 404, { ok: false, error: 'Not found' });
  } catch (err) {
    console.error('[STUDIO ERR]', err);
    sendJson(res, 500, { ok: false, error: err.message });
  }
});

if (import.meta.url === `file://${process.argv[1]}`) {
  server.listen(PORT, '127.0.0.1', () => {
    console.log('====================================================');
    console.log(` Aolon GTS3 Watchface Web Studio aktif!`);
    console.log(` Buka di browser Mac: http://localhost:${PORT}`);
    console.log('====================================================');
  });
}
