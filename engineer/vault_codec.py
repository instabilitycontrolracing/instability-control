"""Lossless packing of iRacing .ibt telemetry for the Drive copy (2026-10-27, telemetry vault).

An .ibt is a header, the session info text, then one fixed-size record per sample (60 a second), each record holding
every channel side by side. Channels change slowly from one sample to the next, so the same bytes stacked in columns
(byte 0 of every record, then byte 1 ...) compress far better than the file as it is. The packed file (.ibtz):

    b"IBTZ" 0x01 | u32 header length | JSON header | xz stream

The xz stream holds the bytes before the records, the records in blocks of BLOCK records turned into columns, then
any bytes after the last whole record. Unpacking gives back the original file bit for bit (its SHA-256 is in the
header and is checked). Anything that doesn't look like an .ibt is packed as plain xz ("mode": "raw").
Only the standard library (lzma) is used, so nothing new to install.
"""
import hashlib, io, json, lzma, os, struct

import numpy as np

MAGIC = b"IBTZ\x01"
BLOCK = 16384                 # records per column block (about 19 MB for the BMW GTP's 1152-byte record)
CHUNK = 8 << 20
PRESET = 6


def ibt_layout(path, size=None):
    """-> (buf_off, buf_len, records) from the file's header, or None when it isn't a usable .ibt. The record count
    comes from the file size (a file iRacing never finished has 0 in its header)."""
    size = os.path.getsize(path) if size is None else size
    if size < 144:
        return None
    with open(path, "rb") as f:
        head = f.read(144)
    try:
        ver = struct.unpack_from("<i", head, 0)[0]
        buf_len = struct.unpack_from("<i", head, 36)[0]
        buf_off = struct.unpack_from("<i", head, 52)[0]
    except struct.error:
        return None
    if ver not in (1, 2) or not (16 <= buf_len <= 1 << 20) or not (144 <= buf_off <= size):
        return None
    recs = (size - buf_off) // buf_len
    return buf_off, buf_len, recs


def _sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def pack(src, dst, sha256=None, preset=PRESET, pace=None):
    """Write src packed to dst (dst is written as is - the caller writes to a temp name and renames).
    pace() is called between blocks (the vault uses it to slow down / wait while you drive). -> header dict."""
    size = os.path.getsize(src)
    lay = ibt_layout(src, size)
    hdr = {"v": 1, "name": os.path.basename(src), "size": size, "sha256": sha256 or _sha_file(src),
           "mode": "cols" if lay and lay[2] > 0 else "raw"}
    if hdr["mode"] == "cols":
        hdr.update(buf_off=lay[0], buf_len=lay[1], recs=lay[2], block=BLOCK)
    hj = json.dumps(hdr, separators=(",", ":")).encode()
    with open(src, "rb") as f, open(dst, "wb") as out:
        out.write(MAGIC + struct.pack("<I", len(hj)) + hj)
        with lzma.LZMAFile(out, "wb", format=lzma.FORMAT_XZ, preset=preset) as z:
            if hdr["mode"] == "raw":
                while True:
                    b = f.read(CHUNK)
                    if not b:
                        break
                    z.write(b)
                    pace and pace()
            else:
                off, bl, recs = lay
                z.write(f.read(off))
                done = 0
                while done < recs:
                    n = min(BLOCK, recs - done)
                    b = f.read(n * bl)
                    a = np.frombuffer(b, np.uint8).reshape(n, bl)
                    z.write(np.ascontiguousarray(a.T).tobytes())
                    done += n
                    pace and pace()
                while True:
                    b = f.read(CHUNK)
                    if not b:
                        break
                    z.write(b)
        out.flush()
        os.fsync(out.fileno())
    return hdr


def read_header(path):
    with open(path, "rb") as f:
        m = f.read(len(MAGIC))
        if m != MAGIC:
            raise ValueError("not a packed telemetry file")
        n = struct.unpack("<I", f.read(4))[0]
        return json.loads(f.read(n).decode()), len(MAGIC) + 4 + n


def unpack_iter(path):
    """Yields the original file's bytes, in order."""
    hdr, start = read_header(path)
    with open(path, "rb") as f:
        f.seek(start)
        with lzma.LZMAFile(f, "rb") as z:
            if hdr["mode"] == "raw":
                while True:
                    b = z.read(CHUNK)
                    if not b:
                        break
                    yield b
                return
            off, bl, recs, blk = hdr["buf_off"], hdr["buf_len"], hdr["recs"], hdr["block"]
            yield _exact(z, off)
            done = 0
            while done < recs:
                n = min(blk, recs - done)
                a = np.frombuffer(_exact(z, n * bl), np.uint8).reshape(bl, n)
                yield np.ascontiguousarray(a.T).tobytes()
                done += n
            while True:
                b = z.read(CHUNK)
                if not b:
                    break
                yield b


def _exact(z, n):
    buf = io.BytesIO()
    while buf.tell() < n:
        b = z.read(n - buf.tell())
        if not b:
            raise ValueError("packed file is cut short")
        buf.write(b)
    return buf.getvalue()


def verify(path, sha256=None):
    """True when the packed file unpacks to exactly the original (size and SHA-256)."""
    hdr, _ = read_header(path)
    h, n = hashlib.sha256(), 0
    for b in unpack_iter(path):
        h.update(b); n += len(b)
    return n == hdr["size"] and h.hexdigest() == hdr["sha256"] and (sha256 is None or sha256 == hdr["sha256"])


def unpack(path, dst):
    """Packed file -> the original .ibt at dst (checked). -> dst"""
    hdr, _ = read_header(path)
    h = hashlib.sha256()
    tmp = dst + ".part"
    with open(tmp, "wb") as out:
        for b in unpack_iter(path):
            h.update(b); out.write(b)
    if h.hexdigest() != hdr["sha256"]:
        os.remove(tmp)
        raise ValueError("unpacked file doesn't match its checksum")
    os.replace(tmp, dst)
    return dst
