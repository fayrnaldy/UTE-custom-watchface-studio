#!/usr/bin/env python3
"""
UTE / Aolon GTS3 (390x450) Watchface (.bin) Unpacker & Compiler Library
Supports 'WF' v2 container + 'PA' (fmt 0x0200) ARGB8565 scanline codec.
Zero external dependencies (uses Python stdlib struct + zlib).
"""
import json
import math
import os
import struct
import sys
import zlib


def write_png(path, width, height, rgba_bytes):
    """Write an RGBA8888 buffer (width * height * 4 bytes) to a PNG file."""
    raw_rows = bytearray()
    stride = width * 4
    for y in range(height):
        raw_rows.append(0)  # filter type 0 (None)
        raw_rows.extend(rgba_bytes[y * stride : (y + 1) * stride])

    def chunk(tag, data):
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    compressed = zlib.compress(bytes(raw_rows), 6)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", compressed))
        f.write(chunk(b"IEND", b""))


def rgb565_to_rgb888(c):
    r5 = (c >> 11) & 0x1F
    g6 = (c >> 5) & 0x3F
    b5 = c & 0x1F
    r8 = (r5 << 3) | (r5 >> 2)
    g8 = (g6 << 2) | (g6 >> 4)
    b8 = (b5 << 3) | (b5 >> 2)
    return r8, g8, b8


def rgb888_to_rgb565_parts(r8, g8, b8):
    r5 = (r8 >> 3) & 0x1F
    g6 = (g8 >> 2) & 0x3F
    b5 = (b8 >> 3) & 0x1F
    c = (r5 << 11) | (g6 << 5) | b5
    return r5, g6, b5, c


def decode_pa(buf):
    """Decode a 'PA' (fmt 0x0200) asset block into (width, height, rgba_bytes)."""
    magic, ver, w, h, fmt, extra = struct.unpack_from("<2sHHHHH", buf, 0)
    if magic != b"PA":
        raise ValueError(f"Expected PA magic, got {magic!r}")
    if fmt != 0x0200:
        raise ValueError(f"Unsupported PA fmt 0x{fmt:04x}")

    tbl = [r * extra + struct.unpack_from("<h", buf, 16 + r * 2)[0] for r in range(h + 1)]
    raw = buf[16 + (h + 1) * 2 :]

    out = bytearray(w * h * 4)
    pos = 0
    for r in range(h):
        line = raw[tbl[r] : tbl[r + 1]]
        i = 0
        pa, pr5, pg6, pb5 = 0, 0, 0, 0
        px = 0
        while i < len(line):
            b = line[i]
            if b < 0x80:
                dr = ((b >> 5) & 0x03) - 2
                dg = ((b >> 2) & 0x07) - 4
                db = (b & 0x03) - 2
                pr5 = (pr5 + dr) & 0x1F
                pg6 = (pg6 + dg) & 0x3F
                pb5 = (pb5 + db) & 0x1F
                c = (pr5 << 11) | (pg6 << 5) | pb5
                r8, g8, b8 = rgb565_to_rgb888(c)
                out[pos : pos + 4] = bytes((r8, g8, b8, pa))
                pos += 4
                px += 1
                i += 1
            elif (b >> 6) == 2:
                cnt = b & 0x3F
                pa = line[i + 1]
                c = line[i + 2] | (line[i + 3] << 8)
                pr5 = (c >> 11) & 0x1F
                pg6 = (c >> 5) & 0x3F
                pb5 = c & 0x1F
                r8, g8, b8 = rgb565_to_rgb888(c)
                pix = bytes((r8, g8, b8, pa))
                for _ in range(cnt):
                    out[pos : pos + 4] = pix
                    pos += 4
                px += cnt
                i += 4
            else:
                cnt = b & 0x3F
                i += 1
                for _ in range(cnt):
                    c = line[i] | (line[i + 1] << 8)
                    i += 2
                    pr5 = (c >> 11) & 0x1F
                    pg6 = (c >> 5) & 0x3F
                    pb5 = c & 0x1F
                    r8, g8, b8 = rgb565_to_rgb888(c)
                    out[pos : pos + 4] = bytes((r8, g8, b8, pa))
                    pos += 4
                px += cnt
        if px != w:
            raise ValueError(f"Row {r} decoded {px} pixels, expected {w}")
    return w, h, bytes(out)


def encode_pa(width, height, rgba_bytes):
    """Encode an RGBA8888 buffer into a 'PA' (fmt 0x0200) compressed asset block."""
    encoded_rows = []
    stride = width * 4

    for y in range(height):
        row = rgba_bytes[y * stride : (y + 1) * stride]
        # Convert row into list of (a, r5, g6, b5, c565)
        pixels = []
        for x in range(width):
            r8, g8, b8, a8 = row[x * 4 : x * 4 + 4]
            if a8 == 0:
                pixels.append((0, 0, 0, 0, 0))
            else:
                r5, g6, b5, c = rgb888_to_rgb565_parts(r8, g8, b8)
                pixels.append((a8, r5, g6, b5, c))

        line_out = bytearray()
        pa, pr5, pg6, pb5 = 0, 0, 0, 0
        x = 0
        while x < width:
            a, r5, g6, b5, c = pixels[x]
            # Count identical consecutive pixels (up to 63)
            run = 1
            while x + run < width and run < 63:
                na, _, _, _, nc = pixels[x + run]
                if na == a and nc == c:
                    run += 1
                else:
                    break

            # If run >= 2, RLE (4 bytes) beats or ties alternatives cleanly
            if run >= 2:
                # Wait: if run <= 3 and exact match with prev (0x52), 1*run bytes < 4 bytes!
                if run <= 3 and a == pa and r5 == pr5 and g6 == pg6 and b5 == pb5:
                    line_out.extend(b"\x52" * run)
                else:
                    line_out.extend(struct.pack("<BBH", 0x80 | run, a, c))
                    pa, pr5, pg6, pb5 = a, r5, g6, b5
                x += run
                continue

            # Single pixel (run == 1): try 1-byte diff if alpha matches!
            if a == pa:
                dr = (r5 - pr5 + 16) % 32 - 16
                dg = (g6 - pg6 + 32) % 64 - 32
                db = (b5 - pb5 + 16) % 32 - 16
                if -2 <= dr <= 1 and -4 <= dg <= 3 and -2 <= db <= 1:
                    op = ((dr + 2) << 5) | ((dg + 4) << 2) | (db + 2)
                    line_out.append(op)
                    pr5, pg6, pb5 = r5, g6, b5
                    x += 1
                    continue

                # Literal stream of same-alpha pixels where RLE/diff doesn't immediately kick in
                lit = [c]
                t_r5, t_g6, t_b5 = r5, g6, b5
                while x + len(lit) < width and len(lit) < 63:
                    na, nr5, ng6, nb5, nc = pixels[x + len(lit)]
                    if na != a:
                        break
                    # Stop if next pixel starts an RLE run >= 2
                    if x + len(lit) + 1 < width:
                        n2a, _, _, _, n2c = pixels[x + len(lit) + 1]
                        if n2a == na and n2c == nc:
                            break
                    # Stop if next pixel can use 1-byte diff from current literal pixel
                    ndr = (nr5 - t_r5 + 16) % 32 - 16
                    ndg = (ng6 - t_g6 + 32) % 64 - 32
                    ndb = (nb5 - t_b5 + 16) % 32 - 16
                    if -2 <= ndr <= 1 and -4 <= ndg <= 3 and -2 <= ndb <= 1:
                        break
                    lit.append(nc)
                    t_r5, t_g6, t_b5 = nr5, ng6, nb5

                line_out.append(0xC0 | len(lit))
                for lc in lit:
                    line_out.extend(struct.pack("<H", lc))
                pa, pr5, pg6, pb5 = a, t_r5, t_g6, t_b5
                x += len(lit)
                continue

            # Alpha changed and run == 1 -> emit 1-pixel ARGB8565 (4 bytes)
            line_out.extend(struct.pack("<BBH", 0x81, a, c))
            pa, pr5, pg6, pb5 = a, r5, g6, b5
            x += 1

        encoded_rows.append(bytes(line_out))

    # Compute cumulative offsets & find best 'extra' stride so all deltas fit int16
    cum = [0]
    for rb in encoded_rows:
        cum.append(cum[-1] + len(rb))
    total_data = cum[-1]
    extra = int(round(total_data / max(1, height)))

    # Verify int16 range
    deltas = [cum[r] - r * extra for r in range(height + 1)]
    if min(deltas) < -32768 or max(deltas) > 32767:
        # Adjust extra to center min/max delta
        # Not linearly independent of r, but average is optimal; check safety
        raise ValueError(f"Row delta overflow: min={min(deltas)}, max={max(deltas)}")

    hdr = struct.pack("<2sHHHHH4s", b"PA", 0x0100, width, height, 0x0200, extra, b"\x00\x00\x00\x00")
    tbl_bytes = b"".join(struct.pack("<h", d) for d in deltas)
    return hdr + tbl_bytes + b"".join(encoded_rows)


def unpack_bin(bin_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    data = open(bin_path, "rb").read()
    wf_id, payload_len, crc, w, h = struct.unpack_from("<IIIHH", data, 0)
    calc_crc = zlib.crc32(data[24:]) & 0xFFFFFFFF
    cnt = struct.unpack_from("<H", data, 0x46)[0]

    manifest = {
        "source": os.path.basename(bin_path),
        "wf_id": wf_id,
        "wf_id_bcd_bytes": data[0x1D:0x20].hex(),
        "width": w,
        "height": h,
        "crc_ok": crc == calc_crc,
        "widgets": [],
    }

    asset_map = {}
    for idx in range(cnt):
        pos = 0x4C + idx * 20
        desc = data[pos : pos + 20]
        off = struct.unpack_from("<I", desc, 0)[0]
        b4, b5, frames, b7 = desc[4], desc[5], desc[6], desc[7]
        x, y = struct.unpack_from("<HH", desc, 8)
        tail = desc[12:20].hex()

        if off not in asset_map:
            ab = 0x18 + off
            magic, ver, aw, ah, fmt, extra = struct.unpack_from("<2sHHHHH", data, ab)
            end_tbl = struct.unpack_from("<h", data, ab + 16 + ah * 2)[0]
            total_len = 16 + (ah + 1) * 2 + ah * extra + end_tbl
            asset_buf = data[ab : ab + total_len]
            png_name = f"asset_{off:06x}_{aw}x{ah}_f{frames}.png"
            if fmt == 0x0200:
                _, _, rgba = decode_pa(asset_buf)
                write_png(os.path.join(out_dir, png_name), aw, ah, rgba)
            else:
                png_name = f"asset_{off:06x}_fmt{fmt:04x}.raw"
                open(os.path.join(out_dir, png_name), "wb").write(asset_buf)
            asset_map[off] = {"file": png_name, "w": aw, "h": ah, "fmt": f"0x{fmt:04x}"}

        manifest["widgets"].append(
            {
                "index": idx,
                "type_hex": f"{b4:02x} {b5:02x}",
                "frames": frames,
                "align_or_digits": b7,
                "x": x,
                "y": y,
                "tail_hex": tail,
                "asset": asset_map[off],
            }
        )

    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def pack_bin(wf_id, wf_bcd_bytes, width, height, widgets_spec):
    """
    Build a complete UTE/Aolon .bin watchface!
    widgets_spec: list of dicts:
      - type_bytes: bytes of length 4 (e.g. bytes([0x02, 0x10, 0x01, 0x00]))
      - x: int (uint16)
      - y: int (uint16)
      - tail_bytes: bytes of length 8
      - asset_key: hashable key to deduplicate shared spritesheets (e.g. 'digits_big')
      - asset_pa: encoded PA bytes (from encode_pa)
    """
    count = len(widgets_spec)
    # Payload layout starting at file offset 0x18 (payload offset 0x00):
    # 0x00..0x27 (40 bytes): 'WF\x0c\x04\x01' + 3-byte BCD ID + 32 zero bytes
    # 0x28..0x33 (12 bytes): <HHHH I -> 1, width, height, count, payload_size
    # 0x34..(0x34 + count*20): descriptors (20 bytes each)
    # Followed immediately by deduplicated PA asset blocks!
    table_end_rel = 0x34 + count * 20

    asset_offsets = {}
    asset_blobs = []
    cur_rel = table_end_rel
    for wspec in widgets_spec:
        key = wspec["asset_key"]
        if key not in asset_offsets:
            asset_offsets[key] = cur_rel
            pa_bytes = wspec["asset_pa"]
            asset_blobs.append(pa_bytes)
            cur_rel += len(pa_bytes)

    payload_size = cur_rel
    wf_hdr = b"WF\x0c\x04\x01" + wf_bcd_bytes + (b"\x00" * 32)
    wf_meta = struct.pack("<HHHHI", 1, width, height, count, payload_size)

    desc_blobs = []
    for wspec in widgets_spec:
        rel_off = asset_offsets[wspec["asset_key"]]
        t4 = wspec["type_bytes"]
        tail8 = wspec["tail_bytes"]
        desc_blobs.append(struct.pack("<I4sHH8s", rel_off, t4, wspec["x"], wspec["y"], tail8))

    payload = wf_hdr + wf_meta + b"".join(desc_blobs) + b"".join(asset_blobs)
    assert len(payload) == payload_size

    crc = zlib.crc32(payload) & 0xFFFFFFFF
    outer = struct.pack(
        "<IIIHH8s",
        wf_id,
        payload_size,
        crc,
        width,
        height,
        b"\x01\x01\x01\x02\x00\x00\x00\x00",
    )
    return outer + payload


if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    cap = os.path.join(base, "captured")
    for fn in sorted(os.listdir(cap)):
        if fn.endswith(".bin"):
            out = os.path.join(base, "unpacked", fn[:-4])
            m = unpack_bin(os.path.join(cap, fn), out)
            print(f"Unpacked {fn} -> {len(m['widgets'])} widgets, crc_ok={m['crc_ok']}")
