# erio.py — 自带容器读写：ER regulation.bin（AES-256-CBC → DCX/ZSTD → BND4）与 DCX 文件
#
# 不依赖任何外部工具。格式来源：SoulsFormats RegulationDecryptor（密钥与 CBC+PKCS7 为公开格式事实）。
#
# 自检：python erio.py --selftest --bin <regulation.bin> --tree <WitchyBND 解包目录>
#   ① 解出 BND4 内所有文件，与解包目录逐字节比对
#   ② 重新打包 + 加密一次，再解一遍，逐字节比对
import argparse, hashlib, os, struct
import zstandard as zstd

MAGIC_DCX = b"DCX\0"
MAGIC_BND4 = b"BND4"
# ER regulation 的 AES-256 密钥（公开格式事实）
ER_REG_KEY = bytes([0x99, 0xBF, 0xFC, 0x36, 0x6A, 0x6B, 0xC8, 0xC6, 0xF5, 0x82, 0x7D, 0x09, 0x36, 0x02, 0xD6, 0x76,
                    0xC4, 0x28, 0x92, 0xA0, 0x1C, 0x20, 0x7F, 0xB0, 0x24, 0xD3, 0xAF, 0x4E, 0x49, 0x3F, 0xEF, 0x99])


def _u32be(b, off):
    return struct.unpack_from(">I", b, off)[0]


# ─────────────────────────── DCX ───────────────────────────
def dcx_parts(data: bytes) -> dict:
    """实测布局：'DCX\\0' + u32BE(unk=0x11000, dcs_off, dcp_off, dca_off, payload_off)"""
    assert data[:4] == MAGIC_DCX, "不是 DCX"
    dcs_off, dcp_off, dca_off, payload_off = (_u32be(data, 8), _u32be(data, 12), _u32be(data, 16), _u32be(data, 20))
    assert data[dcs_off:dcs_off + 3] == b"DCS", f"缺 DCS 段（dsс_off={dcs_off:#x}）"
    unc, comp = _u32be(data, dcs_off + 4), _u32be(data, dcs_off + 8)
    kind = "ZSTD"
    if data[dcp_off:dcp_off + 4] == b"DCP\0":
        kind = data[dcp_off + 4:dcp_off + 8].split(b"\0")[0].decode(errors="replace") or "ZSTD"
    return {"dcs_off": dcs_off, "dcp_off": dcp_off, "dca_off": dca_off, "payload_off": payload_off,
            "unc": unc, "comp": comp, "kind": kind}


def dcx_decompress(data: bytes) -> bytes:
    h = dcx_parts(data)
    payload = data[h["payload_off"]:h["payload_off"] + h["comp"]]
    if h["kind"].upper().startswith("ZSTD"):
        out = zstd.ZstdDecompressor().decompress(payload, max_output_size=max(h["unc"], 1) + 4096)
    elif h["kind"].upper().startswith(("DEFLATE", "ZLIB")):
        import zlib
        out = zlib.decompress(payload)
    else:
        raise ValueError(f"未知 DCX 压缩类型 {h['kind']}")
    assert len(out) == h["unc"], f"解压后大小不符 {len(out)} != {h['unc']}"
    return out


def dcx_compress(raw: bytes, template: bytes = None, level: int = 12) -> bytes:
    """→ DCX(zstd)。给 template（原始 DCX）则沿用它的头、只改大小与载荷（最稳）"""
    # ⚠ 必须对齐 FromSoft 的 ZSTD 帧参数：小窗口、不写内容长度、不写校验和
    #   （用 python-zstandard 的默认参数会被游戏的解码器拒绝 → 启动即崩）
    _params = zstd.ZstdCompressionParameters.from_level(
        level, window_log=16, write_content_size=0, write_checksum=0)
    comp = zstd.ZstdCompressor(compression_params=_params).compress(raw)
    if template is not None:
        h = dcx_parts(template)
        head = bytearray(template[:h["payload_off"]])
        struct.pack_into(">I", head, h["dcs_off"] + 4, len(raw))
        struct.pack_into(">I", head, h["dcs_off"] + 8, len(comp))
        return bytes(head) + comp
    dcs = b"DCS\0" + struct.pack(">II", len(raw), len(comp))
    dcp = b"DCP\0" + b"ZSTD\0\0\0\0" + struct.pack(">I", 0x20) + b"\0" * 0x38
    hsz = 0x18
    dca_off = hsz + len(dcs) + len(dcp)
    head = bytearray(hsz)
    head[0:4] = MAGIC_DCX
    struct.pack_into(">I", head, 4, 0x11000)
    struct.pack_into(">I", head, 8, hsz)
    struct.pack_into(">I", head, 12, hsz + len(dcs))
    struct.pack_into(">I", head, 16, dca_off)
    struct.pack_into(">I", head, 20, dca_off + 8)
    return bytes(head) + dcs + dcp + b"DCA\0" + struct.pack(">I", 8) + comp


# ─────────────────── ER regulation 的 AES 层 ───────────────────
def _aes():
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    return Cipher, algorithms, modes


def regulation_decrypt(path) -> bytes:
    """regulation.bin → DCX 明文（前 16 字节是 IV；CBC/NoPadding）"""
    Cipher, algorithms, modes = _aes()
    data = open(path, "rb").read()
    iv, ct = data[:16], data[16:]
    if len(ct) % 16:
        ct += b"\0" * (16 - len(ct) % 16)
    d = Cipher(algorithms.AES(ER_REG_KEY), modes.CBC(iv)).decryptor()
    return d.update(ct) + d.finalize()


def regulation_encrypt(dcx_bytes: bytes, out_path: str) -> int:
    """DCX 明文 → regulation.bin（零 IV + PKCS7）"""
    Cipher, algorithms, modes = _aes()
    from cryptography.hazmat.primitives import padding
    pt = padding.PKCS7(128).padder()
    body = pt.update(dcx_bytes) + pt.finalize()
    enc = Cipher(algorithms.AES(ER_REG_KEY), modes.CBC(bytes(16))).encryptor()
    open(out_path, "wb").write(bytes(16) + enc.update(body) + enc.finalize())
    return len(dcx_bytes)


# ─────────────────────────── BND4 ───────────────────────────
class Bnd4:
    def __init__(self, files):
        self.files = list(files)                 # [(name, data)]
        self.dcx_template = None

    @classmethod
    def parse(cls, data: bytes):
        assert data[:4] == MAGIC_BND4, "不是 BND4"
        _unk04, _version, file_count, header_size = struct.unpack_from("<IiII", data, 4)
        fmt_off = _u32be(data, header_size) if header_size + 4 <= len(data) else 0
        fmt_off = struct.unpack_from("<I", data, header_size)[0]
        files, spans, e = [], [], fmt_off
        for _ in range(file_count):
            # 实测条目（0x24）：flags u32 | id u32 | size u64 | size2 u64 | 数据偏移 u32 | 序号 u32 | 名字偏移 u32
            data_size = struct.unpack_from("<Q", data, e + 0x08)[0]
            data_off = struct.unpack_from("<I", data, e + 0x18)[0]
            name_off = struct.unpack_from("<I", data, e + 0x20)[0]
            i = name_off                                   # UTF-16LE、以 \0\0 结尾（按 2 字节步进找，避免错位）
            while i + 1 < len(data) and data[i:i + 2] != b"\0\0":
                i += 2
            name = data[name_off:i].decode("utf-16-le", "replace")
            files.append((name, data[data_off:data_off + data_size]))
            spans.append((name, data_off, data_size))
            e += 0x24
        obj = cls(files)
        obj.spans = spans                # [(name, offset, size)] —— 用于"原地改写"
        obj.header = data[:0x40]
        obj.raw_entries = [data[fmt_off + 0x24 * i: fmt_off + 0x24 * (i + 1)] for i in range(file_count)]
        first_name = min(spans, key=lambda x: struct.unpack_from("<I", data, fmt_off + 0x24 * spans.index(x) + 0x20)[0]) if spans else None
        name_start = struct.unpack_from("<I", data, fmt_off + 0x20)[0]
        data_start = struct.unpack_from("<I", data, 0x28)[0]
        obj.raw_names = data[name_start:data_start]          # 名字区原样保留
        obj.name_start = name_start
        obj.data_start = data_start
        return obj

    def build(self) -> bytes:
        """按实测布局重建 BND4（保留原头部模板，只更新条目数/数据区起点/各条目偏移与大小）"""
        n = len(self.files)
        header = bytearray(getattr(self, "header", bytes(0x40)))
        if len(header) < 0x40:
            header = bytearray(0x40)
            header[:4] = MAGIC_BND4
        header_size = 0x40
        fmt_off = header_size
        entry_bytes = 0x24 * n
        names_off = fmt_off + entry_bytes
        raw_names = getattr(self, "raw_names", None)
        name_start = getattr(self, "name_start", names_off)
        if raw_names:                                        # 沿用原名字区（一字不改）
            nb = bytearray(raw_names)
            names_size = len(nb)
            data_off = name_start + names_size
        else:
            nb, name_ofs = bytearray(), []
            for name, _d in self.files:
                name_ofs.append(names_off + len(nb))
                nb += name.encode("utf-16-le") + b"\0\0"
            names_size = len(nb)
            data_off = names_off + names_size
        chunks, offs, pos = [], [], 0
        for _n, d in self.files:
            pad = (-pos) % 2
            if pad:
                chunks.append(b"\0" * pad)
            offs.append(data_off + pos + pad)
            chunks.append(d)
            pos += pad + len(d)
        out = bytearray(name_start)
        out[:header_size] = header
        struct.pack_into("<I", out, 0x0C, n)              # 条目数
        struct.pack_into("<I", out, 0x10, header_size)
        struct.pack_into("<I", out, 0x20, 0x24)           # 条目大小
        struct.pack_into("<I", out, 0x28, data_off)       # 数据区起点
        e = fmt_off
        raw_entries = getattr(self, "raw_entries", None) or []
        for i, (_nm, d) in enumerate(self.files):
            # 尽量沿用原条目里的非几何字段（flags / id / 序号），只更新大小与偏移
            if i < len(raw_entries):
                old_e = raw_entries[i]
                flags, fid = struct.unpack_from("<II", old_e, 0)
                index = struct.unpack_from("<I", old_e, 0x1C)[0]
            else:
                flags, fid, index = 0x40, 0xFFFFFFFF, i
            struct.pack_into("<I", out, e, flags)
            struct.pack_into("<I", out, e + 0x04, fid)
            struct.pack_into("<Q", out, e + 0x08, len(d))
            struct.pack_into("<Q", out, e + 0x10, len(d))
            struct.pack_into("<I", out, e + 0x18, offs[i])
            struct.pack_into("<I", out, e + 0x1C, index)
            nof = struct.unpack_from("<I", raw_entries[i], 0x20)[0] if i < len(raw_entries) else name_ofs[i]
            struct.pack_into("<I", out, e + 0x20, nof)
            e += 0x24
        return bytes(out) + bytes(nb) + b"".join(chunks)

    def get(self, name):
        for n, d in self.files:
            if n == name:
                return d
        return None

    def set(self, name, data):
        for i, (n, _d) in enumerate(self.files):
            if n == name:
                self.files[i] = (n, data)
                return True
        self.files.append((name, data))
        return False


# ─────────────────────────── 组合 ───────────────────────────
def read_regulation(path) -> Bnd4:
    data = open(path, "rb").read()
    if data[:4] == MAGIC_DCX:
        tpl, raw = data, dcx_decompress(data)
    elif data[:4] == MAGIC_BND4:
        tpl, raw = None, data
    else:                                        # ER：AES → DCX → BND4
        tpl = regulation_decrypt(path)
        raw = dcx_decompress(tpl)
    bnd = Bnd4.parse(raw)
    bnd.dcx_template = tpl
    return bnd


def write_regulation(path, bnd: Bnd4, encrypt=True, level=12) -> int:
    dcx = dcx_compress(bnd.build(), getattr(bnd, "dcx_template", None), level)
    if encrypt:
        regulation_encrypt(dcx, path)
    else:
        open(path, "wb").write(dcx)
    return len(dcx)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--bin", default="")
    ap.add_argument("--tree", default="")
    a = ap.parse_args()
    if not a.selftest:
        return 0
    bnd = read_regulation(a.bin)
    print(f"  读到 {len(bnd.files)} 个文件")
    bad = miss = 0
    for name, data in bnd.files:
        p = os.path.join(a.tree, name)
        if not os.path.exists(p):
            miss += 1
            continue
        if hashlib.sha256(data).hexdigest() != hashlib.sha256(open(p, "rb").read()).hexdigest():
            bad += 1
            print(f"   [X] {name} 内容不符")
    print(f"  ① 读取比对：{len(bnd.files)} 个文件，内容不符 {bad}，解包目录缺 {miss}")
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "_rt_reg.bin")
    write_regulation(tmp, bnd)
    bnd2 = read_regulation(tmp)
    bad2 = sum(1 for (n1, d1), (n2, d2) in zip(bnd.files, bnd2.files) if n1 != n2 or d1 != d2)
    print(f"  ② 回写再读：{len(bnd2.files)} 个文件，不符 {bad2}（产物 {os.path.getsize(tmp)} B vs 原 {os.path.getsize(a.bin)} B）")
    return 0 if bad == 0 and miss == 0 and bad2 == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


def patch_container(raw: bytes, edits, ) -> bytes:
    """在容器明文里原地改写内部文件（尺寸必须完全相同）→ 返回新的明文"""
    out = bytearray(raw)
    for name, new_bytes in edits:
        span = next((s for s in getattr(Bnd4.parse(raw), "spans", []) if s[0] == name), None)
        if span is None:
            raise KeyError(f"容器里没有 {name}")
        _n, off, size = span
        if len(new_bytes) != size:
            raise ValueError(f"{name} 尺寸变化（{size} → {len(new_bytes)}），原地改写不可用")
        out[off:off + size] = new_bytes
    return bytes(out)
