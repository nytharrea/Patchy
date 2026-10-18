import re
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

MANIFEST_ENTRY = "AndroidManifest.xml"
MAX_LABEL_LENGTH = 255

XML_DOCUMENT = 0x0003
STRING_POOL = 0x0001
RESOURCE_MAP = 0x0180
START_ELEMENT = 0x0102
END_ELEMENT = 0x0103

UTF8_FLAG = 0x100
SORTED_FLAG = 0x1
POOL_HEADER_SIZE = 28
NODE_HEADER_SIZE = 16
ATTRIBUTE_SIZE = 20

TYPE_REFERENCE = 0x01
TYPE_STRING = 0x03

LABEL_ATTRIBUTE_ID = 0x01010001
NAME_ATTRIBUTE_ID = 0x01010003
ANDROID_NAMESPACE = "http://schemas.android.com/apk/res/android"

LAUNCHER_CATEGORIES = frozenset({"android.intent.category.LAUNCHER", "android.intent.category.LEANBACK_LAUNCHER"})
LAUNCHER_ACTIVITIES = frozenset({"activity", "activity-alias"})

REFERENCE_TEXT = re.compile(r"^[@?](?:[A-Za-z_][\w.]*:)?[A-Za-z_][\w.]*/[A-Za-z_][\w.$]*$")


class LabelError(Exception):
    pass


@dataclass(frozen=True)
class LabelChange:
    element: str
    before: str
    after: str
    forced: bool


@dataclass(frozen=True)
class _Pool:
    start: int
    end: int
    strings: list[str]


@dataclass
class _Element:
    name: str
    parent: int | None
    label_offset: int | None = None
    label_type: int = 0
    label_data: int = 0
    label_text: str | None = None
    android_name: str | None = None
    launcher: bool = False


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _read_length8(data: bytes, offset: int) -> tuple[int, int]:
    first = data[offset]
    if first & 0x80:
        return ((first & 0x7F) << 8) | data[offset + 1], offset + 2
    return first, offset + 1


def _read_length16(data: bytes, offset: int) -> tuple[int, int]:
    first = _u16(data, offset)
    if first & 0x8000:
        return ((first & 0x7FFF) << 16) | _u16(data, offset + 2), offset + 4
    return first, offset + 2


def _length8(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    if length <= 0x7FFF:
        return bytes([(length >> 8) | 0x80, length & 0xFF])
    raise LabelError("the app name is too long")


def _length16(length: int) -> bytes:
    if length < 0x8000:
        return struct.pack("<H", length)
    return struct.pack("<HH", (length >> 16) | 0x8000, length & 0xFFFF)


def _encode_string(text: str, utf8: bool) -> bytes:
    if utf8:
        raw = text.encode("utf-8")
        units = len(text.encode("utf-16-le")) // 2
        return _length8(units) + _length8(len(raw)) + raw + b"\x00"
    raw = text.encode("utf-16-le")
    return _length16(len(raw) // 2) + raw + b"\x00\x00"


def _parse_pool(data: bytes, start: int) -> _Pool:
    if len(data) < start + POOL_HEADER_SIZE:
        raise LabelError(f"{MANIFEST_ENTRY} is truncated before its string pool")
    kind, header_size, size, count, style_count, flags, strings_start, _ = struct.unpack_from(
        "<HHIIIIII", data, start
    )
    end = start + size
    if kind != STRING_POOL or header_size < POOL_HEADER_SIZE or size < header_size or end > len(data):
        raise LabelError(f"{MANIFEST_ENTRY} has no valid string pool")
    offsets_end = header_size + 4 * (count + style_count)
    if offsets_end > size or strings_start < offsets_end or strings_start > size:
        raise LabelError(f"{MANIFEST_ENTRY} has a string pool with an unexpected layout")

    utf8 = bool(flags & UTF8_FLAG)
    base = start + strings_start
    strings: list[str] = []
    try:
        for index in range(count):
            position = base + _u32(data, start + header_size + 4 * index)
            if position >= end:
                raise LabelError(f"{MANIFEST_ENTRY} has a string that lies outside its string pool")
            if utf8:
                _, position = _read_length8(data, position)
                length, position = _read_length8(data, position)
                strings.append(data[position : position + length].decode("utf-8", errors="replace"))
            else:
                length, position = _read_length16(data, position)
                strings.append(data[position : position + 2 * length].decode("utf-16-le", errors="replace"))
    except (struct.error, IndexError) as e:
        raise LabelError(f"{MANIFEST_ENTRY} has a damaged string pool") from e
    return _Pool(start, end, strings)


def _string(pool: _Pool, index: int) -> str:
    return pool.strings[index] if index < len(pool.strings) else ""


def _read_element(
    data: bytes, position: int, size: int, pool: _Pool, resource_ids: list[int], parent: int | None
) -> _Element:
    if size < NODE_HEADER_SIZE + 20:
        raise LabelError(f"{MANIFEST_ENTRY} has an element that is too short")
    _, name_index, attribute_start, attribute_size, attribute_count, _, _, _ = struct.unpack_from(
        "<IIHHHHHH", data, position + NODE_HEADER_SIZE
    )
    first = position + NODE_HEADER_SIZE + attribute_start
    if attribute_size < ATTRIBUTE_SIZE or first + attribute_size * attribute_count > position + size:
        raise LabelError(f"{MANIFEST_ENTRY} has an element with damaged attributes")

    element = _Element(_string(pool, name_index), parent)
    for index in range(attribute_count):
        offset = first + attribute_size * index
        namespace, name, _, _, _, data_type, value = struct.unpack_from("<IIIHBBI", data, offset)
        attribute_id = resource_ids[name] if name < len(resource_ids) else 0
        unmapped = attribute_id == 0 and _string(pool, namespace) == ANDROID_NAMESPACE
        attribute_name = _string(pool, name)
        text = _string(pool, value) if data_type == TYPE_STRING else None
        if attribute_id == LABEL_ATTRIBUTE_ID or (unmapped and attribute_name == "label"):
            element.label_offset = offset
            element.label_type = data_type
            element.label_data = value
            element.label_text = text
        elif attribute_id == NAME_ATTRIBUTE_ID or (unmapped and attribute_name == "name"):
            element.android_name = text
    return element


def _mark_launchers(elements: list[_Element]) -> None:
    for element in elements:
        if element.name != "category" or element.android_name not in LAUNCHER_CATEGORIES:
            continue
        parent = element.parent
        while parent is not None:
            ancestor = elements[parent]
            if ancestor.name in LAUNCHER_ACTIVITIES:
                ancestor.launcher = True
                break
            parent = ancestor.parent


def _parse_manifest(data: bytes) -> tuple[_Pool, list[_Element], int]:
    if len(data) < 8 or _u16(data, 0) != XML_DOCUMENT or _u16(data, 2) != 8:
        raise LabelError(f"{MANIFEST_ENTRY} is not a compiled Android XML file")
    total = _u32(data, 4)
    if total < 8 or total > len(data):
        raise LabelError(f"{MANIFEST_ENTRY} is truncated")

    pool = _parse_pool(data, 8)
    resource_ids: list[int] = []
    elements: list[_Element] = []
    stack: list[int] = []
    position = pool.end
    while position + 8 <= total:
        kind, header_size, size = struct.unpack_from("<HHI", data, position)
        if size < 8 or header_size > size or position + size > total:
            raise LabelError(f"{MANIFEST_ENTRY} has a damaged chunk at offset {position}")
        if kind == RESOURCE_MAP:
            count = (size - header_size) // 4
            resource_ids = list(struct.unpack_from(f"<{count}I", data, position + header_size))
        elif kind == START_ELEMENT:
            elements.append(_read_element(data, position, size, pool, resource_ids, stack[-1] if stack else None))
            stack.append(len(elements) - 1)
        elif kind == END_ELEMENT and stack:
            stack.pop()
        position += size

    _mark_launchers(elements)
    return pool, elements, total


def _append_string(pool: bytes, text: str) -> tuple[bytes, int]:
    kind, header_size, _, count, style_count, flags, strings_start, styles_start = struct.unpack_from(
        "<HHIIIIII", pool, 0
    )
    if style_count or styles_start:
        raise LabelError(f"the string pool of {MANIFEST_ENTRY} holds styled strings")

    offsets = pool[header_size : header_size + 4 * count]
    gap = pool[header_size + 4 * count : strings_start]
    block = pool[strings_start:]
    new_offset = len(block)
    block += _encode_string(text, bool(flags & UTF8_FLAG))
    block += b"\x00" * (-len(block) % 4)

    new_strings_start = strings_start + 4
    header = struct.pack(
        "<HHIIIIII",
        kind,
        header_size,
        new_strings_start + len(block),
        count + 1,
        0,
        flags & ~SORTED_FLAG,
        new_strings_start,
        0,
    )
    offsets += struct.pack("<I", new_offset)
    return header + pool[POOL_HEADER_SIZE:header_size] + offsets + gap + block, count


def _describe(element: _Element) -> str:
    if element.label_type == TYPE_STRING:
        return element.label_text or ""
    if element.label_type == TYPE_REFERENCE:
        return f"@0x{element.label_data:08x}"
    return f"value of type 0x{element.label_type:02x}"


def rewrite_manifest(manifest: bytes, label: str | None, fallback: str) -> tuple[bytes, list[LabelChange]]:
    pool, elements, total = _parse_manifest(manifest)
    targets = [
        element
        for element in elements
        if element.label_offset is not None and (element.name == "application" or element.launcher)
    ]
    if label is not None and not targets:
        raise LabelError(f"{MANIFEST_ENTRY} has no android:label to set")

    planned: list[tuple[_Element, bool]] = []
    for element in targets:
        if label is not None:
            if element.label_type == TYPE_STRING and element.label_text == label:
                continue
            planned.append((element, True))
        elif element.label_text is not None and REFERENCE_TEXT.match(element.label_text):
            planned.append((element, False))
    if not planned:
        return manifest, []

    text = label if label is not None else fallback
    if not text.strip() or len(text) > MAX_LABEL_LENGTH:
        raise LabelError(f"the app name must be between 1 and {MAX_LABEL_LENGTH} characters long")
    try:
        text.encode("utf-16-le")
    except UnicodeEncodeError as e:
        raise LabelError("the app name contains characters that cannot be stored") from e

    changes = [LabelChange(element.name, _describe(element), text, forced) for element, forced in planned]
    new_pool, index = _append_string(manifest[pool.start : pool.end], text)
    rest = bytearray(manifest[pool.end : total])
    for element, _ in planned:
        assert element.label_offset is not None
        offset = element.label_offset - pool.end
        struct.pack_into("<I", rest, offset + 8, index)
        struct.pack_into("<HBB", rest, offset + 12, 8, 0, TYPE_STRING)
        struct.pack_into("<I", rest, offset + 16, index)

    result = bytearray(manifest[: pool.start]) + new_pool + rest
    struct.pack_into("<I", result, 4, len(result))
    return bytes(result), changes


def _copy_with_manifest(source: Path, target: Path, manifest: bytes) -> None:
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w") as rewritten:
        for info in original.infolist():
            clone = zipfile.ZipInfo(info.filename, info.date_time)
            clone.compress_type = info.compress_type
            clone.external_attr = info.external_attr
            clone.create_system = info.create_system
            payload = manifest if info.filename == MANIFEST_ENTRY else original.read(info)
            rewritten.writestr(clone, payload, compress_type=info.compress_type)


def _verify_copy(source: Path, target: Path, manifest: bytes, label: str | None, fallback: str) -> None:
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target) as rewritten:
        before = original.infolist()
        after = rewritten.infolist()
        if [info.filename for info in before] != [info.filename for info in after]:
            raise LabelError("the rewritten APK lists different files than the original")
        for old, new in zip(before, after, strict=True):
            if old.filename == MANIFEST_ENTRY:
                continue
            if (old.CRC, old.file_size, old.compress_type) != (new.CRC, new.file_size, new.compress_type):
                raise LabelError(f"{old.filename} changed while the APK was rewritten")
        if rewritten.read(MANIFEST_ENTRY) != manifest:
            raise LabelError(f"{MANIFEST_ENTRY} was not written as expected")
        broken = rewritten.testzip()
        if broken is not None:
            raise LabelError(f"{broken} is damaged in the rewritten APK")
    if rewrite_manifest(manifest, label, fallback)[1]:
        raise LabelError("the app name is still not fixed after rewriting the manifest")


def fix_apk_label(apk: Path, label: str | None, fallback: str) -> list[LabelChange]:
    try:
        with zipfile.ZipFile(apk) as archive:
            manifest = archive.read(MANIFEST_ENTRY)
    except (OSError, KeyError, zipfile.BadZipFile) as e:
        raise LabelError(f"cannot read {MANIFEST_ENTRY} from {apk.name}: {e}") from e

    updated, changes = rewrite_manifest(manifest, label, fallback)
    if not changes:
        return []

    temporary = apk.with_name(apk.name + ".label.tmp")
    try:
        _copy_with_manifest(apk, temporary, updated)
        _verify_copy(apk, temporary, updated, label, fallback)
        temporary.replace(apk)
    except (OSError, zipfile.BadZipFile) as e:
        raise LabelError(f"cannot rewrite {apk.name}: {e}") from e
    finally:
        temporary.unlink(missing_ok=True)
    return changes
