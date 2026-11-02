import struct
import zipfile
from pathlib import Path

from patchy.engine.label import MANIFEST_ENTRY, _parse_manifest

ANDROID_URI = "http://schemas.android.com/apk/res/android"
LABEL_ID = 0x01010001
NAME_ID = 0x01010003
LAUNCHER = "android.intent.category.LAUNCHER"
MAIN = "android.intent.action.MAIN"

STRING = 0x03
REFERENCE = 0x01
NONE = 0xFFFFFFFF

FIXED_STRINGS = [
    "label",
    "name",
    "android",
    ANDROID_URI,
    "manifest",
    "package",
    "application",
    "activity",
    "intent-filter",
    "action",
    "category",
    "com.example.app",
    MAIN,
    LAUNCHER,
    ".Main",
    ".Other",
    "Other",
]

Label = tuple[int, str | int] | None


def text_label(text: str) -> Label:
    return (STRING, text)


def reference_label(resource_id: int) -> Label:
    return (REFERENCE, resource_id)


class _Strings:
    def __init__(self) -> None:
        self.items: list[str] = []
        for text in FIXED_STRINGS:
            self.add(text)

    def add(self, text: str) -> int:
        if text not in self.items:
            self.items.append(text)
        return self.items.index(text)


def _length8(length: int) -> bytes:
    return bytes([length]) if length < 0x80 else bytes([(length >> 8) | 0x80, length & 0xFF])


def _entry(text: str, utf8: bool) -> bytes:
    if utf8:
        raw = text.encode("utf-8")
        return _length8(len(text.encode("utf-16-le")) // 2) + _length8(len(raw)) + raw + b"\x00"
    raw = text.encode("utf-16-le")
    return struct.pack("<H", len(raw) // 2) + raw + b"\x00\x00"


def string_pool(strings: list[str], utf8: bool, styles: int = 0) -> bytes:
    data = bytearray()
    offsets = []
    for text in strings:
        offsets.append(len(data))
        data += _entry(text, utf8)
    data += b"\x00" * (-len(data) % 4)
    strings_start = 28 + 4 * len(strings) + 4 * styles
    size = strings_start + len(data)
    header = struct.pack("<HHIIIIII", 1, 28, size, len(strings), styles, 0x100 if utf8 else 0, strings_start, 0)
    return (
        header + b"".join(struct.pack("<I", offset) for offset in offsets) + b"\x00" * (4 * styles) + bytes(data)
    )


def _attribute(namespace: int, name: int, raw: int, data_type: int, data: int) -> bytes:
    return struct.pack("<IIIHBBI", namespace, name, raw, 8, 0, data_type, data)


def _start(name: int, attributes: list[bytes]) -> bytes:
    body = struct.pack("<IIHHHHHH", NONE, name, 20, 20, len(attributes), 0, 0, 0) + b"".join(attributes)
    return struct.pack("<HHIII", 0x0102, 16, 16 + len(body), 1, NONE) + body


def _end(name: int) -> bytes:
    body = struct.pack("<II", NONE, name)
    return struct.pack("<HHIII", 0x0103, 16, 16 + len(body), 1, NONE) + body


def _namespace(kind: int, prefix: int, uri: int) -> bytes:
    body = struct.pack("<II", prefix, uri)
    return struct.pack("<HHIII", kind, 16, 16 + len(body), 1, NONE) + body


def build_manifest(
    app: Label,
    launcher: Label = None,
    other: str = "Other",
    utf8: bool = True,
    styles: int = 0,
) -> bytes:
    strings = _Strings()
    index = strings.add
    android = index(ANDROID_URI)

    def label_attribute(label: Label) -> list[bytes]:
        if label is None:
            return []
        kind, value = label
        if kind == STRING:
            assert isinstance(value, str)
            position = index(value)
            return [_attribute(android, 0, position, STRING, position)]
        assert isinstance(value, int)
        return [_attribute(android, 0, NONE, REFERENCE, value)]

    def name_attribute(value: str) -> bytes:
        position = index(value)
        return _attribute(android, 1, position, STRING, position)

    package = index("com.example.app")
    nodes = [
        _namespace(0x0100, index("android"), android),
        _start(index("manifest"), [_attribute(NONE, index("package"), package, STRING, package)]),
        _start(index("application"), label_attribute(app)),
        _start(index("activity"), label_attribute(launcher) + [name_attribute(".Main")]),
        _start(index("intent-filter"), []),
        _start(index("action"), [name_attribute(MAIN)]),
        _end(index("action")),
        _start(index("category"), [name_attribute(LAUNCHER)]),
        _end(index("category")),
        _end(index("intent-filter")),
        _end(index("activity")),
        _start(index("activity"), label_attribute(text_label(other)) + [name_attribute(".Other")]),
        _end(index("activity")),
        _end(index("application")),
        _end(index("manifest")),
        _namespace(0x0101, index("android"), android),
    ]

    pool = string_pool(strings.items, utf8, styles)
    resource_map = struct.pack("<HHI", 0x0180, 8, 8 + 8) + struct.pack("<II", LABEL_ID, NAME_ID)
    body = pool + resource_map + b"".join(nodes)
    return struct.pack("<HHI", 0x0003, 8, 8 + len(body)) + body


def apk_labels(apk: Path) -> list[tuple[str, int, str | None]]:
    with zipfile.ZipFile(apk) as archive:
        _, elements, _ = _parse_manifest(archive.read(MANIFEST_ENTRY))
    return [(e.name, e.label_type, e.label_text) for e in elements if e.label_offset is not None]


def build_apk(path: Path, manifest: bytes) -> Path:
    entries = [
        ("AndroidManifest.xml", manifest, zipfile.ZIP_DEFLATED),
        ("resources.arsc", bytes(range(256)) * 8, zipfile.ZIP_STORED),
        ("classes.dex", b"dex\n035\x00" + bytes(range(256)) * 40, zipfile.ZIP_DEFLATED),
        ("lib/arm64-v8a/libnative.so", b"\x7fELF" + bytes(4096), zipfile.ZIP_STORED),
        ("res/layout/main.xml", b"<layout/>", zipfile.ZIP_DEFLATED),
        ("assets/", b"", zipfile.ZIP_STORED),
    ]
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload, method in entries:
            info = zipfile.ZipInfo(name, (2026, 10, 17, 9, 0, 0))
            info.compress_type = method
            info.external_attr = 0o644 << 16
            archive.writestr(info, payload, compress_type=method)
    return path
