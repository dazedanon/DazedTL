"""Ruby Marshal 4.8 reading and writing for RPG Maker VX Ace data.

Loading keeps everything a later dump needs: object identity (so links are
written where Ruby writes them), instance-variable order, string encodings
and the raw bytes of user-defined types such as Table, Color and Tone.
Dumping follows Ruby 3.4's writer, which is what RV2JSON runs on: equal
flonum floats are written once and linked afterwards, integers beyond 32 bits
become bignums, and user-defined objects are remembered after their data.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Any

MAJOR, MINOR = 4, 8


class MarshalError(ValueError):
    """The data is not a Ruby Marshal stream this module can read or write."""


@dataclass(eq=False)
class Symbol:
    """A Ruby Symbol. Symbols are equal by name and written once per dump."""

    name: bytes
    # True for a UTF-8 name with non-ASCII bytes; Ruby writes no encoding
    # for ASCII names.
    utf8: bool = False

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Symbol) and other.name == self.name

    def __hash__(self) -> int:
        return hash(self.name)

    @property
    def text(self) -> str:
        return self.name.decode("utf-8", "surrogateescape")


def sym(name: str) -> Symbol:
    data = name.encode("utf-8", "surrogateescape")
    return Symbol(data, not data.isascii())


@dataclass(eq=False)
class RString:
    """A Ruby String: its bytes, encoding and any other instance variables."""

    data: bytes
    # "UTF-8", "US-ASCII", another Ruby encoding name, or None for binary
    # (ASCII-8BIT) strings, which Ruby writes without an encoding.
    encoding: str | None = "UTF-8"
    ivars: list[tuple[Symbol, Any]] = field(default_factory=list)

    @classmethod
    def utf8(cls, text: str) -> RString:
        return cls(text.encode("utf-8"), "UTF-8")

    def same_text(self, other: object) -> bool:
        """Ruby's String#== for strings with compatible encodings."""
        return isinstance(other, RString) and other.data == self.data


@dataclass(eq=False)
class RObject:
    """A plain Ruby object: its class name and ordered instance variables."""

    cls: str
    # Keys include the "@" prefix; insertion order is Ruby's ivar order.
    ivars: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str, default: Any = None) -> Any:
        return self.ivars.get(name, default)


@dataclass(eq=False)
class RUserDef:
    """An object dumped through _dump, such as Table, Color or Tone."""

    cls: str
    data: bytes
    # Instance variables of the dumped string, such as its encoding.
    data_encoding: str | None = None


@dataclass(eq=False)
class RHash:
    """A Ruby Hash: ordered pairs, which may use any Ruby value as a key."""

    pairs: list[tuple[Any, Any]] = field(default_factory=list)
    default: Any = None
    has_default: bool = False
    # Instance variables set on the Hash itself, which some scripts use.
    ivars: list[tuple[Symbol, Any]] = field(default_factory=list)

    def get(self, key: Any, default: Any = None) -> Any:
        for item, value in self.pairs:
            if item == key and type(item) is type(key):
                return value
        return default


_fstrings: dict[tuple[bytes, str | None], RString] = {}


def hash_key(key: Any) -> Any:
    """The key a Ruby Hash stores: an unfrozen String key becomes the one
    frozen, deduplicated string for its text (rb_hash_key_str), so equal keys
    are one object and later uses are written as links."""
    if isinstance(key, RString) and not key.ivars:
        return _fstrings.setdefault((key.data, key.encoding), key)
    return key


class HeapFloat(float):
    """A Float Ruby keeps on the heap (not a flonum), so it has identity."""


def is_flonum(value: float) -> bool:
    """Whether 64-bit Ruby stores this double as an immediate flonum."""
    bits = struct.unpack("<Q", struct.pack("<d", value))[0]
    if bits == 0:
        return True
    top = (bits >> 60) & 0x7
    return bits != 0x3000000000000000 and top in (3, 4)


def ruby_float(value: float) -> float:
    """A float as Ruby would hold it after loading."""
    return float(value) if is_flonum(value) else HeapFloat(value)


# ---------------------------------------------------------------------------
# Loading


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.symbols: list[Symbol] = []
        self.objects: list[Any] = []

    def byte(self) -> int:
        if self.pos >= len(self.data):
            raise MarshalError("Unexpected end of Marshal data.")
        value = self.data[self.pos]
        self.pos += 1
        return value

    def take(self, count: int) -> bytes:
        if count < 0 or self.pos + count > len(self.data):
            raise MarshalError("Unexpected end of Marshal data.")
        value = self.data[self.pos : self.pos + count]
        self.pos += count
        return value

    def long(self) -> int:
        c = self.byte()
        if c >= 128:
            c -= 256
        if c == 0:
            return 0
        if 4 < c < 128:
            return c - 5
        if -129 < c < -4:
            return c + 5
        if c > 0:
            value = 0
            for i in range(c):
                value |= self.byte() << (8 * i)
            return value
        count = -c
        value = -1
        for i in range(count):
            value &= ~(0xFF << (8 * i))
            value |= self.byte() << (8 * i)
        return value

    def bytes_(self) -> bytes:
        return self.take(self.long())

    def entry(self, value: Any) -> Any:
        self.objects.append(value)
        return value

    def symbol(self) -> Symbol:
        kind = chr(self.byte())
        if kind == ";":
            index = self.long()
            if index >= len(self.symbols):
                raise MarshalError("Marshal symbol link points past the symbols read.")
            return self.symbols[index]
        if kind == "I":
            if chr(self.byte()) != ":":
                raise MarshalError("Expected a symbol.")
            result = self._symbol_body()
            for _ in range(self.long()):
                key = self.symbol()
                value = self.value()
                if key.name in (b"E", b"encoding") and value not in (False, None):
                    result.utf8 = True
            return result
        if kind != ":":
            raise MarshalError("Expected a symbol, found " + repr(kind) + ".")
        return self._symbol_body()

    def _symbol_body(self) -> Symbol:
        result = Symbol(self.bytes_())
        self.symbols.append(result)
        return result

    def _ivars(self) -> list[tuple[Symbol, Any]]:
        return [(self.symbol(), self.value()) for _ in range(self.long())]

    @staticmethod
    def _encoding(ivars: list[tuple[Symbol, Any]]) -> tuple[str | None, list]:
        encoding: str | None = None
        rest = []
        for key, value in ivars:
            if key.name == b"E":
                encoding = "UTF-8" if value is True else "US-ASCII"
            elif key.name == b"encoding" and isinstance(value, RString):
                encoding = value.data.decode("ascii")
            else:
                rest.append((key, value))
        return encoding, rest

    def value(self) -> Any:
        kind = chr(self.byte())
        if kind == "0":
            return None
        if kind == "T":
            return True
        if kind == "F":
            return False
        if kind == "i":
            return self.long()
        if kind == ":" or kind == ";":
            self.pos -= 1
            return self.symbol()
        if kind == "@":
            index = self.long()
            if index >= len(self.objects):
                raise MarshalError("Marshal link points past the objects read.")
            return self.objects[index]
        if kind == "I":
            return self._with_ivars()
        if kind == "f":
            text = self.bytes_()
            return self.entry(_parse_float(text))
        if kind == "l":
            sign = chr(self.byte())
            count = self.long()
            digits = self.take(count * 2)
            number = int.from_bytes(digits, "little")
            return self.entry(-number if sign == "-" else number)
        if kind == '"':
            return self.entry(RString(self.bytes_(), None))
        if kind == "[":
            result: list[Any] = self.entry([])
            for _ in range(self.long()):
                result.append(self.value())
            return result
        if kind in "{}":
            result_hash = self.entry(RHash())
            for _ in range(self.long()):
                key = self.value()
                result_hash.pairs.append((hash_key(key), self.value()))
            if kind == "}":
                result_hash.default = self.value()
                result_hash.has_default = True
            return result_hash
        if kind == "o":
            cls = self.symbol().text
            obj = self.entry(RObject(cls))
            for key, value in self._ivars():
                obj.ivars[key.text] = value
            return obj
        if kind == "u":
            cls = self.symbol().text
            return self.entry(RUserDef(cls, self.bytes_()))
        raise MarshalError("Unsupported Marshal value type " + repr(kind) + ".")

    def _with_ivars(self) -> Any:
        kind = chr(self.byte())
        if kind == '"':
            string = self.entry(RString(self.bytes_(), None))
            string.encoding, string.ivars = self._encoding(self._ivars())
            return string
        if kind == "u":
            cls = self.symbol().text
            data = self.bytes_()
            encoding, _rest = self._encoding(self._ivars())
            return self.entry(RUserDef(cls, data, encoding))
        if kind == ":":
            self.pos -= 2
            return self.symbol()
        if kind in "{}":
            self.pos -= 1
            result = self.value()
            result.ivars = self._ivars()
            return result
        raise MarshalError("Unsupported Marshal value with ivars " + repr(kind) + ".")


def _parse_float(text: bytes) -> float:
    if text == b"inf":
        return HeapFloat(math.inf)
    if text == b"-inf":
        return HeapFloat(-math.inf)
    if text == b"nan":
        return HeapFloat(math.nan)
    # Old writers append a binary mantissa after a NUL; the decimal text
    # already round-trips, which is how Ruby 1.9 and later write floats.
    return ruby_float(float(text.split(b"\0", 1)[0].decode("ascii")))


def load(data: bytes) -> Any:
    """Loads one Marshal stream, as Ruby's Marshal.load does."""
    if len(data) < 2 or data[0] != MAJOR or data[1] > MINOR:
        raise MarshalError("This is not Ruby Marshal 4.8 data.")
    reader = _Reader(data)
    reader.pos = 2
    return reader.value()


# ---------------------------------------------------------------------------
# Dumping


def ruby_float_digits(value: float) -> tuple[str, int, bool]:
    """The shortest round-trip digits of a float, as ruby_dtoa mode 0 gives
    them: (digits, decimal point position, negative)."""
    text = repr(abs(value))
    negative = math.copysign(1.0, value) < 0
    mantissa, _, exponent = text.partition("e")
    whole, _, fraction = mantissa.partition(".")
    digits = (whole + fraction).lstrip("0")
    leading = len(whole + fraction) - len((whole + fraction).lstrip("0"))
    decpt = len(whole) - leading + (int(exponent) if exponent else 0)
    digits = digits.rstrip("0") or "0"
    return digits, decpt, negative


def marshal_float_text(value: float) -> bytes:
    """Ruby's w_float text for a float."""
    if math.isinf(value):
        return b"-inf" if value < 0 else b"inf"
    if math.isnan(value):
        return b"nan"
    if value == 0.0:
        return b"-0" if math.copysign(1.0, value) < 0 else b"0"
    digits, decpt, negative = ruby_float_digits(value)
    sign = "-" if negative else ""
    count = len(digits)
    if decpt < -3 or decpt > count:
        text = digits[0] + ("." + digits[1:] if count > 1 else "")
        text += "e" + str(decpt - 1)
    elif decpt > 0:
        text = digits[:decpt] + ("." + digits[decpt:] if count > decpt else "")
    else:
        text = "0." + "0" * -decpt + digits
    return (sign + text).encode("ascii")


class _Writer:
    def __init__(self) -> None:
        self.out = bytearray([MAJOR, MINOR])
        self.symbols: dict[bytes, int] = {}
        self.objects: dict[Any, int] = {}
        self.entries = 0
        self.encoding_names: dict[str, RString] = {}

    def long(self, value: int) -> None:
        if not -(2**31) <= value < 2**31:
            raise MarshalError("long too big to dump")
        if value == 0:
            self.out.append(0)
        elif 0 < value < 123:
            self.out.append(value + 5)
        elif -124 < value < 0:
            self.out.append((value - 5) & 0xFF)
        else:
            body = bytearray()
            for i in range(1, 5):
                body.append(value & 0xFF)
                value >>= 8
                if value == 0:
                    self.out.append(i)
                    break
                if value == -1:
                    self.out.append(256 - i)
                    break
            self.out += body

    def bytes_(self, data: bytes) -> None:
        self.long(len(data))
        self.out += data

    def remember(self, key: Any) -> None:
        self.objects[key] = self.entries
        self.entries += 1

    def symbol(self, value: Symbol) -> None:
        index = self.symbols.get(value.name)
        if index is not None:
            self.out += b";"
            self.long(index)
            return
        if value.utf8:
            self.out += b"I"
        self.out += b":"
        self.bytes_(value.name)
        self.symbols[value.name] = len(self.symbols)
        if value.utf8:
            self.long(1)
            self.symbol(Symbol(b"E"))
            self.out += b"T"

    def link(self, key: Any) -> bool:
        index = self.objects.get(key)
        if index is None:
            return False
        self.out += b"@"
        self.long(index)
        return True

    def encoding(self, name: str | None) -> None:
        """Writes a string's encoding ivar, as Ruby's w_encoding does."""
        if name == "UTF-8" or name == "US-ASCII":
            self.symbol(Symbol(b"E"))
            self.value(name == "UTF-8")
        elif name is not None:
            self.symbol(Symbol(b"encoding"))
            # Ruby reuses one name string per encoding, so later uses link.
            cached = self.encoding_names.setdefault(
                name, RString(name.encode("ascii"), None)
            )
            self.value(cached)

    def value(self, value: Any) -> None:
        if value is None:
            self.out += b"0"
        elif value is True:
            self.out += b"T"
        elif value is False:
            self.out += b"F"
        elif isinstance(value, int):
            self.integer(value)
        elif isinstance(value, Symbol):
            self.symbol(value)
        elif isinstance(value, float):
            self.float_(value)
        elif self.link(id(value)):
            return
        elif isinstance(value, RString):
            self.remember(id(value))
            extra = len(value.ivars) + (value.encoding is not None)
            if extra:
                self.out += b"I"
            self.out += b'"'
            self.bytes_(value.data)
            if extra:
                self.long(extra)
                self.encoding(value.encoding)
                for key, item in value.ivars:
                    self.symbol(key)
                    self.value(item)
        elif isinstance(value, list):
            self.remember(id(value))
            self.out += b"["
            self.long(len(value))
            for item in value:
                self.value(item)
        elif isinstance(value, RHash):
            self.remember(id(value))
            if value.ivars:
                self.out += b"I"
            self.out += b"}" if value.has_default else b"{"
            self.long(len(value.pairs))
            for key, item in value.pairs:
                self.value(key)
                self.value(item)
            if value.has_default:
                self.value(value.default)
            if value.ivars:
                self.long(len(value.ivars))
                for key, item in value.ivars:
                    self.symbol(key)
                    self.value(item)
        elif isinstance(value, RObject):
            self.remember(id(value))
            self.out += b"o"
            self.symbol(sym(value.cls))
            self.long(len(value.ivars))
            for key, item in value.ivars.items():
                self.symbol(sym(key))
                self.value(item)
        elif isinstance(value, RUserDef):
            data = _userdef_dump(value)
            if value.data_encoding is not None:
                self.out += b"I"
            self.out += b"u"
            self.symbol(sym(value.cls))
            self.bytes_(data)
            if value.data_encoding is not None:
                self.long(1)
                self.encoding(value.data_encoding)
            # Ruby remembers a user-defined object after its data.
            self.remember(id(value))
        else:
            raise MarshalError(
                "Cannot dump a " + type(value).__name__ + " as Ruby data."
            )

    def integer(self, value: int) -> None:
        # Ruby tests the tagged VALUE (2n+1) against 31 bits, so only
        # integers within 30 bits are written as fixnums.
        if -(2**30) <= value < 2**30:
            self.out += b"i"
            self.long(value)
            return
        # Larger integers are bignums: written as 16-bit digits, and they use
        # a link index although nothing links to them.
        self.out += b"l"
        self.out += b"-" if value < 0 else b"+"
        magnitude = abs(value)
        shorts = (magnitude.bit_length() + 15) // 16
        self.long(shorts)
        self.out += magnitude.to_bytes(shorts * 2, "little")
        self.entries += 1

    def float_(self, value: float) -> None:
        # Flonums are immediates in 64-bit Ruby, so equal ones are one object;
        # other floats are heap objects with their own identity.
        key: Any = (
            ("flonum", struct.pack("<d", value)) if is_flonum(value) else id(value)
        )
        if self.link(key):
            return
        self.remember(key)
        self.out += b"f"
        self.bytes_(marshal_float_text(value))


def _userdef_dump(value: RUserDef) -> bytes:
    """The _dump result of a user-defined object, as RV2JSON's classes give it."""
    if value.cls == "Tone" and len(value.data) == 32:
        # Tone._load clamps through its setters, so a re-dump writes the
        # clamped values.
        red, green, blue, gray = struct.unpack("<4d", value.data)
        return tone_bytes(red, green, blue, gray)
    return value.data


def _clamp(value: float, low: float, high: float) -> float:
    # Ruby's [[low, value].max, high].min, which keeps the first of equals.
    bounded = value if value > low else low
    return bounded if bounded <= high else high


def tone_bytes(red: float, green: float, blue: float, gray: float) -> bytes:
    return struct.pack(
        "<4d",
        _clamp(red, -255, 255),
        _clamp(green, -255, 255),
        _clamp(blue, -255, 255),
        _clamp(gray, 0, 255),
    )


def color_bytes(red: float, green: float, blue: float, alpha: float) -> bytes:
    return struct.pack("<4d", red, green, blue, alpha)


def dump(value: Any) -> bytes:
    """Dumps one value as Ruby 3.4's Marshal.dump would."""
    writer = _Writer()
    writer.value(value)
    return bytes(writer.out)
