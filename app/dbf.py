"""Bounded, read-only preview of a dBASE attribute table.

Shapefile attributes live in .dbf, which is a fixed-width binary format. The
preview deliberately leaves geometry and the source file untouched.
"""

import codecs
import os
import struct


MAX_ROWS = 2000


def _encoding(path, character_fields, sample, language_driver):
    stem = os.path.splitext(path)[0]
    directory = os.path.dirname(path)
    sidecar = next((os.path.join(directory, name) for name in os.listdir(directory)
                    if name.lower() == os.path.basename(stem).lower() + ".cpg"), None)
    if sidecar:
        with open(sidecar, "rb") as file:
            declared = file.read(128).decode("ascii", errors="ignore").strip().lstrip("\ufeff")
        declared = {"65001": "utf-8", "1256": "cp1256", "1252": "cp1252"}.get(declared, declared)
        try:
            return codecs.lookup(declared).name
        except LookupError:
            pass

    # Some exporters omit .cpg and the language byte. Check the actual text
    # bytes before picking a single-byte fallback, especially for Persian data.
    chunks = []
    for record in sample:
        offset = 1
        for field in character_fields:
            raw = record[offset:offset + field[2]].strip(b" \x00")
            if field[1] in {"C", "M"} and raw:
                chunks.append(raw)
            offset += field[2]
    text = b" ".join(chunks)
    if not text:
        return "latin-1" if language_driver == 0x57 else "cp1252" if language_driver == 0x03 else "utf-8"
    try:
        text.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    persian = text.decode("cp1256", errors="replace")
    letters = sum(char.isalpha() for char in persian)
    arabic = sum("\u0600" <= char <= "\u06ff" for char in persian)
    if letters and arabic / letters > 0.2:
        return "cp1256"
    return "cp1252" if language_driver == 0x03 else "latin-1"


def _value(raw, kind, decimals, encoding):
    if kind == "I" and len(raw) == 4:
        return struct.unpack("<i", raw)[0]
    if kind == "B" and len(raw) == 8:
        return struct.unpack("<d", raw)[0]
    if kind in {"C", "M"}:
        return raw.rstrip(b" \x00").decode(encoding, errors="replace")
    value = raw.strip(b" \x00").decode("ascii", errors="replace")
    if not value or set(value) == {"*"}:
        return None
    if kind in {"N", "F"}:
        try:
            return float(value) if decimals or "." in value or "e" in value.lower() else int(value)
        except ValueError:
            return value
    if kind == "L":
        return True if value.upper() in {"Y", "T"} else False if value.upper() in {"N", "F"} else None
    if kind == "D" and len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def read_table(path, limit=MAX_ROWS):
    """Return JSON-safe columns and rows; reject malformed or truncated DBF."""
    with open(path, "rb") as file:
        header = file.read(32)
        if len(header) != 32 or header[0] not in {0x03, 0x30, 0x83, 0x8b, 0xf5}:
            raise ValueError("not a supported DBF file")
        count, header_size, record_size = struct.unpack_from("<IHH", header, 4)
        if not 33 <= header_size <= 65535 or not 1 <= record_size <= 65535:
            raise ValueError("invalid DBF header")
        if count and os.path.getsize(path) < header_size + count * record_size:
            raise ValueError("truncated DBF records")
        descriptors = file.read(header_size - 32)
        fields = []
        for pos in range(0, len(descriptors), 32):
            entry = descriptors[pos:pos + 32]
            if not entry or entry[0] == 0x0d:
                break
            if len(entry) < 32 or len(fields) >= 255:
                raise ValueError("invalid DBF field definitions")
            fields.append((entry[:11].split(b"\x00", 1)[0], chr(entry[11]), entry[16], entry[17]))
        if not fields or 1 + sum(field[2] for field in fields) > record_size:
            raise ValueError("invalid DBF record width")
        file.seek(header_size)
        sample = [file.read(record_size) for _ in range(min(count, 32))]
        encoding = _encoding(path, fields, sample, header[29])
        columns = [name.decode(encoding, errors="replace") for name, _, _, _ in fields]
        file.seek(header_size)
        rows = []
        for _ in range(count):
            record = file.read(record_size)
            if len(record) != record_size:
                raise ValueError("truncated DBF record")
            if record[0] == ord("*"):
                continue
            values = []
            pos = 1
            for _, kind, width, decimals in fields:
                values.append(_value(record[pos:pos + width], kind, decimals, encoding))
                pos += width
            rows.append(values)
            if len(rows) >= limit:
                break
    return {"columns": columns, "rows": rows, "total": count, "truncated": count > len(rows), "encoding": encoding}
