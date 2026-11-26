"""Binary DBF previews must render columns and Persian text, not raw bytes."""
import os
import struct
import tempfile
import unittest

from app.dbf import read_table


def make_dbf(path, encoding="utf-8"):
    fields = [("TYPEI", "N", 4, 0), ("TYPEII", "C", 48, 0),
              ("WIDTH", "N", 4, 0), ("NAME", "C", 64, 0)]
    header_size = 32 + len(fields) * 32 + 1
    record_size = 1 + sum(field[2] for field in fields)
    header = bytearray(32)
    header[0] = 3
    struct.pack_into("<IHH", header, 4, 3, header_size, record_size)
    with open(path, "wb") as file:
        file.write(header)
        for name, kind, width, decimals in fields:
            descriptor = bytearray(32)
            descriptor[:len(name)] = name.encode("ascii")
            descriptor[11] = ord(kind)
            descriptor[16] = width
            descriptor[17] = decimals
            file.write(descriptor)
        file.write(b"\r")
        def row(flag, values):
            file.write(flag + b"".join(value.encode(encoding).ljust(field[2], b" ")
                                   for value, field in zip(values, fields)))
        first_name = "خيابان آزادي" if encoding == "cp1256" else "خیابان آزادی"
        second_name = "خيابان رودكي" if encoding == "cp1256" else "خیابان رودکی"
        row(b" ", ["4", "جمع و پخش کننده", "10", first_name])
        row(b"*", ["9", "deleted", "1", "old"])
        row(b" ", ["2", "شرياني درجه 1" if encoding == "cp1256" else "شریانی درجه ۱", "30", second_name])


class DbfPreviewTests(unittest.TestCase):
    def test_utf8_without_cpg(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "roads.dbf")
            make_dbf(path)
            result = read_table(path)
            self.assertEqual(result["columns"], ["TYPEI", "TYPEII", "WIDTH", "NAME"])
            self.assertEqual(result["rows"][0], [4, "جمع و پخش کننده", 10, "خیابان آزادی"])
            self.assertEqual(len(result["rows"]), 2)
            self.assertEqual(result["encoding"], "utf-8")

    def test_cp1256_with_cpg_and_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "roads.dbf")
            make_dbf(path, "cp1256")
            with open(os.path.join(directory, "roads.cpg"), "w", encoding="ascii") as file:
                file.write("1256")
            result = read_table(path, limit=1)
            self.assertEqual(result["rows"], [[4, "جمع و پخش کننده", 10, "خيابان آزادي"]])
            self.assertEqual(result["encoding"], "cp1256")
            self.assertTrue(result["truncated"])

    def test_cp1256_without_cpg(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "roads.dbf")
            make_dbf(path, "cp1256")
            result = read_table(path)
            self.assertEqual(result["encoding"], "cp1256")
            self.assertEqual(result["rows"][1][3], "خيابان رودكي")

    def test_rejects_invalid_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "bad.dbf")
            with open(path, "wb") as file:
                file.write(b"not a DBF")
            with self.assertRaises(ValueError):
                read_table(path)


if __name__ == "__main__":
    unittest.main()
