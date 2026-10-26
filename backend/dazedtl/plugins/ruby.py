"""String literals of RPG Maker VX Ace (RGSS3) Ruby scripts, with exact byte
spans and the text Ruby makes of them, read without running Ruby.

Plugin files translates a script's player text the way it translates a
JavaScript plugin's, so this gives the same inventory syntax.cjs gives for
JavaScript. Like Ruby's own lexer, it decides from what came before whether
`/`, `%`, `?` and `<<` start a literal: after a value they are operators, where
an expression starts they begin a regular expression, a percent literal, a
character or a heredoc, and after a method name that takes arguments without
parentheses, a space before and none after makes them a literal
(`puts %w(a b)` but `x / 2`). Comments, regular expressions and plain symbols
are not text; quoted symbols, commands and character literals are listed but
never translated.

Most literals span their quotes, as JavaScript ones do. A heredoc spans only
its body and a word of a %w list only the word, so the text around them,
delimiters included, stays outside every span.

Ruby 2.6 agreed with it on 589 RGSS3 scripts and Ruby library files: with
every literal it found replaced by a marker, each file still compiled and no
Japanese string was left, and each plain literal's text matched a string
Ruby compiled.
"""

import re
from typing import NoReturn

from dazedtl.languages import JAPANESE, source_pattern

KEYWORDS = {
    "BEGIN",
    "END",
    "alias",
    "and",
    "begin",
    "break",
    "case",
    "class",
    "def",
    "defined?",
    "do",
    "else",
    "elsif",
    "end",
    "ensure",
    "false",
    "for",
    "if",
    "in",
    "module",
    "next",
    "nil",
    "not",
    "or",
    "redo",
    "rescue",
    "retry",
    "return",
    "self",
    "super",
    "then",
    "true",
    "undef",
    "unless",
    "until",
    "when",
    "while",
    "yield",
    "__FILE__",
    "__LINE__",
    "__ENCODING__",
}
# Keywords that are values, so an operator follows them.
VALUES = {
    "end",
    "false",
    "nil",
    "redo",
    "retry",
    "self",
    "true",
    "__FILE__",
    "__LINE__",
    "__ENCODING__",
}
# Keywords that take arguments the way a method call does.
CALLS = {"defined?", "super", "yield"}
# Operators whose operand is compared, not shown.
COMPARISONS = {"==", "!=", "===", "=~", "!~", "<=>"}
# Methods whose argument names code or a file, never text.
LOADERS = {"require", "require_relative", "load"}
# Methods that match text against their argument, as JavaScript's
# startsWith and indexOf do.
MATCHERS = {"start_with?", "index"}
PAIRS = {"(": ")", "[": "]", "{": "}", "<": ">"}
ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "f": "\f",
    "v": "\v",
    "a": "\a",
    "b": "\b",
    "e": "\x1b",
    "s": " ",
}
IDENTIFIER = re.compile(r"[A-Za-z_\u0080-\U0010ffff][\w\u0080-\U0010ffff]*")
NUMBER = re.compile(
    r"0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO]?[0-7_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?r?i?"
)
# Method names that are operators, after def, a dot or a symbol's colon.
OPERATOR_NAME = re.compile(
    r"\[\]=?|<=>|===?|=~|![=~]?|\*\*|[+\-]@?|[*/%~&|^`]|<<|>>|<=?|>=?"
)
HEREDOC = re.compile(
    r"<<([-~]?)(?:([A-Za-z_\u0080-\U0010ffff][\w\u0080-\U0010ffff]*)|\"([^\"\n]*)\"|'([^'\n]*)'|`([^`\n]*)`)"
)
GLOBAL = re.compile(
    r"\$(?:-\w|[~*$?!@/\\;,.=:<>\"&`'+0]|\d+|[A-Za-z_\u0080-\U0010ffff][\w\u0080-\U0010ffff]*)"
)
OPERATOR = re.compile(
    r"\*\*=|<=>|===|<<=|>>=|&&=|\|\|=|\.\.\.|==|!=|=~|!~|=>|->|<=|>=|<<|>>|&&|\|\||\*\*|\.\.|::|&\.|[-+*/%&|^]=|[-+*/%&|^~!<>=.,;:?()\[\]{}]"
)
SPACE = " \t\f\v\r"
BLOCK_COMMENT = re.compile(r"=begin(?=[ \t\r\n]|$)")
BLOCK_END = re.compile(r"^=end(?=[ \t\r\n]|$)", re.MULTILINE)
DATA_END = re.compile(r"__END__\r?(?:\n|$)")
IDENTIFIER_CHAR = re.compile(r"[\w\u0080-\U0010ffff]")


class Unreadable(ValueError):
    """The script holds Ruby this reader can't follow; the file stays
    unchanged."""


def parse(path, source):
    """The script's string literals, as syntax.cjs lists JavaScript's: each
    with its byte span, source text, the text Ruby makes of it, its embedded
    expressions and whether its role keeps it unchanged."""
    result = {"path": path, "language": "ruby", "plugins": []}
    try:
        return {**result, "issues": [], "literals": Lexer(source).run()}
    except Unreadable as exc:
        return {**result, "issues": [str(exc)], "literals": []}


class Lexer:
    def __init__(self, source):
        self.s = source
        self.n = len(source)
        self.i = 0
        # What the next token may be: "beg" where an expression starts,
        # "end" after a value, "arg" after a method name that may take
        # arguments without parentheses, "fname" after def and "dot" after
        # a method call's dot.
        self.state = "beg"
        self.space = False
        self.locals = set()
        self.literals = []
        # Significant tokens, for the context of each literal.
        self.tokens = []
        self.heredocs = []
        self.braces = []
        self.when = False
        self.binary = False
        self.lines = [m.start() for m in re.finditer("\n", source)]

    def fail(self, message, at=None) -> NoReturn:
        line = self.line(self.i if at is None else at)
        raise Unreadable(f"Its Ruby {message} on line {line}.")

    def line(self, index):
        low, high = 0, len(self.lines)
        while low < high:
            middle = (low + high) // 2
            if self.lines[middle] < index:
                low = middle + 1
            else:
                high = middle
        return low + 1

    def run(self):
        self.line_start()
        self.code()
        self.context()
        offsets = self.offsets()
        for literal in self.literals:
            start, end = literal.pop("_span")
            literal.update(
                start=offsets(start),
                end=offsets(end),
                raw=self.s[start:end],
                line=self.line(start),
                column=start - (self.s.rfind("\n", 0, start) + 1) + 1,
                path=[],
            )
            literal.pop("_token", None)
            literal.pop("_tokens", None)
        self.literals.sort(key=lambda literal: literal["start"])
        return self.literals

    def offsets(self):
        """Byte offsets of character positions, as UTF-8 counts them."""
        table, total = [0], 0
        for char in self.s:
            total += len(char.encode("utf-8", "surrogatepass"))
            table.append(total)
        return table.__getitem__

    # Tokens

    def token(self, kind, text, state, **extra):
        self.tokens.append({"kind": kind, "text": text, **extra})
        self.state = state
        self.space = False

    def code(self, embedded=False):
        """Lexes code up to the end, or for an embedded #{...} up to its
        closing brace, whose position it returns."""
        depth = 0
        s = self.s
        while self.i < self.n:
            char = s[self.i]
            if char == "\n":
                self.newline()
                continue
            if char in SPACE:
                self.i += 1
                self.space = True
                continue
            if char == "\\" and s.startswith(("\n", "\r\n"), self.i + 1):
                self.i += 2 if s[self.i + 1] == "\n" else 3
                self.space = True
                continue
            if char == "#":
                end = s.find("\n", self.i)
                self.i = self.n if end < 0 else end
                continue
            if embedded and char == "}" and depth == 0:
                return self.i
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            self.next_token()
        if embedded:
            self.fail("has an embedded expression that never closes")
        return self.n

    def newline(self):
        self.i += 1
        if self.heredocs:
            self.bodies()
        if self.state not in ("beg", "dot", "fname") or not self.tokens:
            self.tokens.append({"kind": "newline", "text": "\n"})
        if self.state not in ("beg", "dot", "fname"):
            self.state = "beg"
            self.when = False
        elif self.tokens and self.tokens[-1]["text"] != ",":
            self.when = False
        self.space = True
        self.line_start()

    def line_start(self):
        """Skips =begin comments and everything after __END__."""
        s = self.s
        while BLOCK_COMMENT.match(s, self.i):
            end = BLOCK_END.search(s, self.i + 6)
            if not end:
                self.fail("has a =begin comment that never ends")
            line = s.find("\n", end.start())
            self.i = self.n if line < 0 else line + 1
        if DATA_END.match(s, self.i):
            self.i = self.n

    def next_token(self):
        s, i = self.s, self.i
        char = s[i]
        state = self.state
        space = self.space
        after = s[i + 1] if i + 1 < self.n else ""
        # A literal may start here where an expression or an argument starts.
        argument = state == "beg" or (
            state == "arg" and space and after not in SPACE + "\n="
        )
        # An operator method's name, after def or a dot.
        match = (state == "fname" or state == "dot" and char != "(") and (
            OPERATOR_NAME.match(s, i)
        )
        if match:
            self.i = match.end()
            self.token("name", match.group(), "end" if state == "fname" else "arg")
            if state == "fname":
                self.parameters()
            return
        if char == '"':
            self.quoted(i, i + 1, '"', None, "double")
        elif char == "'":
            self.quoted(i, i + 1, "'", None, "single")
        elif char == "`":
            self.quoted(i, i + 1, "`", None, "double", kind="command")
        elif char == "/" and argument:
            self.pattern(i + 1, "/", None)
        elif (
            (char == "%" and argument and self.percent())
            or (char == "<" and after == "<" and argument and self.heredoc())
            or (char == "?" and state in ("beg", "arg") and self.character())
            or (char == ":" and after != ":" and self.symbol())
        ):
            # Each reads its literal or symbol when one starts here.
            return
        elif char == "$" and (match := GLOBAL.match(s, i)):
            self.i = match.end()
            self.token("value", match.group(), "end")
        elif char == "@":
            match = re.compile(
                r"@@?[A-Za-z_\u0080-\U0010ffff][\w\u0080-\U0010ffff]*"
            ).match(s, i)
            if not match:
                self.fail("has a stray @")
            self.i = match.end()
            self.token("value", match.group(), "end")
        elif char.isdigit() and (match := NUMBER.match(s, i)):
            self.i = match.end()
            self.token("value", match.group(), "end")
        elif match := IDENTIFIER.match(s, i):
            self.identifier(match)
        else:
            self.operator()

    def identifier(self, match):
        s = self.s
        name, end = match.group(), match.end()
        # A method name may end in ? or !, unless that starts != or ?=.
        if (
            end < self.n
            and s[end] in "?!"
            and (s[end + 1 : end + 2] != "=" or s[end + 2 : end + 3] in ("=", "~", ">"))
        ):
            name, end = name + s[end], end + 1
        state = self.state
        self.i = end
        if state == "fname":
            if s.startswith(".", end) and not s.startswith("..", end):
                # def self.name: the name follows the dot.
                self.i = end + 1
                self.token("name", name, "fname")
                return
            self.token("name", name, "end")
            self.parameters()
            return
        if state == "dot":
            self.token("ident", name, "arg")
            return
        # A label, such as key: in a hash or a keyword argument.
        if (
            s.startswith(":", end)
            and not s.startswith("::", end)
            and state in ("beg", "arg")
            and name[-1] not in "?!"
        ):
            self.i = end + 1
            self.token("label", name, "beg")
            return
        if name in KEYWORDS:
            if name == "def":
                self.token("keyword", name, "fname")
            elif name == "when":
                self.when = True
                self.token("keyword", name, "beg")
            elif name == "then":
                self.when = False
                self.token("keyword", name, "beg")
            elif name == "do":
                self.token("keyword", name, "beg")
                self.block_parameters()
            elif name == "for":
                self.token("keyword", name, "beg")
                found = re.compile(r"([^\n]*?)\bin\b").match(s, self.i)
                if found:
                    self.locals.update(IDENTIFIER.findall(found.group(1)))
            elif name in VALUES:
                self.token("keyword", name, "end")
            elif name in CALLS:
                self.token("ident", name, "arg")
            else:
                self.token("keyword", name, "beg")
            return
        assignment = re.compile(
            r"[ \t]*(?:=(?![=~>])|(?:\|\||&&|\*\*|<<|>>|[-+*/%|&^])=)"
        ).match(s, end)
        if assignment and name[-1] not in "?!":
            self.locals.add(name)
        if name in self.locals or name[0].isupper():
            self.token("value", name, "end")
        else:
            self.token("ident", name, "arg")

    def parameters(self):
        """A method's parameters are its local variables."""
        s = self.s
        match = re.compile(r"[ \t]*\(([^)]*)\)|[ \t]+([^\n;#]*)").match(s, self.i)
        if match:
            self.locals.update(
                name
                for name in IDENTIFIER.findall(match.group(1) or match.group(2) or "")
                if name not in KEYWORDS
            )

    def block_parameters(self):
        match = re.compile(r"\s*\|([^|]*)\|").match(self.s, self.i)
        if match:
            self.locals.update(IDENTIFIER.findall(match.group(1)))

    def operator(self):
        s, i = self.s, self.i
        match = OPERATOR.match(s, i)
        if not match:
            self.fail("has a character it can't read (" + s[i] + ")")
        text = match.group()
        self.i = match.end()
        index = False
        if text in (")", "]"):
            state = "end"
        elif text == "}":
            state = "end"
            if self.braces:
                self.braces.pop()
        elif text in (".", "&.", "::"):
            state = "dot"
        elif text == "[":
            # x[...] after a value or a method name looks up; x [...] passes
            # an array to the method.
            index = self.state in ("end", "arg") and not self.space
            state = "beg"
        elif text == "{":
            self.braces.append(i)
            state = "beg"
        elif text == ";":
            self.when = False
            state = "beg"
        else:
            state = "beg"
        self.token("operator", text, state, index=index)
        if text == "{":
            self.block_parameters()
        elif text == "=>":
            match = re.compile(r"[ \t]*([a-z_]\w*)[ \t]*(?:\r?\n|;|then\b)").match(
                s, self.i
            )
            statement = []
            for token in reversed(self.tokens):
                if token["kind"] == "newline":
                    break
                statement.append(token["text"])
            if match and "rescue" in statement:
                self.locals.add(match.group(1))

    # Literals

    def literal(self, start, end, value, expressions, kind, protected=False):
        protected, self.binary = protected or self.binary, False
        self.literals.append(
            {
                "_span": (start, end),
                "_token": len(self.tokens),
                "_tokens": self.tokens,
                "value": value,
                "expressions": expressions,
                "protected": protected,
                "matcher": False,
                "kind": kind,
            }
        )
        return self.literals[-1]

    def quoted(self, start, at, close, open_, mode, kind=None):
        """A quoted string from its opening delimiter at `start`, its text
        from `at`."""
        end, value, expressions = self.text(at, close, open_, mode)
        literal = self.literal(
            start,
            end + 1,
            value,
            expressions,
            kind or ("template" if expressions else "literal"),
            protected=kind in ("command", "symbol"),
        )
        literal["when"] = self.when
        self.i = end + 1
        self.token("string", "", "end")

    def text(self, at, close, open_, mode, limit=None):
        """The text Ruby makes of a string's source from `at` up to its
        closing delimiter (or `limit` for a heredoc body), as (end, value,
        expressions): double-quoted text has escapes and #{} interpolation,
        single-quoted only \\\\ and an escaped delimiter, raw none."""
        s = self.s
        stop = self.n if limit is None else limit
        j, depth, parts, expressions = at, 0, [], []
        while j < stop:
            char = s[j]
            if close is not None and char == close and depth == 0:
                return j, "".join(parts), expressions
            if open_ is not None and char == open_:
                depth += 1
            elif open_ is not None and char == close:
                depth -= 1
            if char == "\r" and s.startswith("\n", j + 1):
                parts.append("\n")
                j += 2
                continue
            if char == "\\" and mode != "raw" and j + 1 < stop:
                following = s[j + 1]
                if mode == "single":
                    if following == "\\" or following in (close, open_):
                        parts.append(following)
                    else:
                        parts.append("\\" + following)
                    j += 2
                    continue
                j = self.escape(j, parts)
                continue
            if char == "#" and mode == "double" and j + 1 < stop:
                following = s[j + 1]
                if following == "{":
                    finish = self.embedded(j + 2)
                    expression = s[j + 2 : finish]
                    expressions.append(expression)
                    parts.append("#{" + expression + "}")
                    j = finish + 1
                    continue
                match = re.compile(
                    r"#(?:@@?|\$)[A-Za-z_\u0080-\U0010ffff][\w\u0080-\U0010ffff]*"
                ).match(s, j)
                if match:
                    expressions.append(match.group()[1:])
                    parts.append(match.group())
                    j = match.end()
                    continue
            parts.append(char)
            j += 1
        if limit is not None:
            return stop, "".join(parts), expressions
        self.fail("has a string that never closes", at)

    def embedded(self, at):
        """Lexes #{...} code from `at` on its own, so the tokens around the
        string stay its neighbours; returns its closing brace's position.
        Strings inside are part of the outer string's code, as in
        syntax.cjs: changing one changes that code, so none is listed."""
        saved = self.state, self.space, self.when, self.tokens, self.i
        count = len(self.literals)
        self.state, self.space, self.tokens, self.i = "beg", False, [], at
        finish = self.code(embedded=True)
        self.state, self.space, self.when, self.tokens, self.i = saved
        del self.literals[count:]
        return finish

    def escape(self, j, parts):
        """A double-quoted escape at `j`, as Ruby reads it; returns where
        the text continues."""
        s = self.s
        following = s[j + 1]
        if following == "\n":
            return j + 2
        if following == "\r" and s.startswith("\n", j + 2):
            return j + 3
        if following in ESCAPES:
            parts.append(ESCAPES[following])
            return j + 2
        if following in "01234567":
            end = j + 2
            while end < min(j + 4, self.n) and s[end] in "01234567":
                end += 1
            code = int(s[j + 1 : end], 8) & 0xFF
            self.byte(code, j)
            parts.append(chr(code))
            return end
        if following == "x":
            end = j + 2
            while end < min(j + 4, self.n) and s[end] in "0123456789abcdefABCDEF":
                end += 1
            if end == j + 2:
                self.fail("has an invalid \\x escape", j)
            code = int(s[j + 2 : end], 16)
            self.byte(code, j)
            parts.append(chr(code))
            return end
        if following == "u":
            match = re.compile(
                r"\{[ \t]*([0-9a-fA-F]{1,6}(?:[ \t]+[0-9a-fA-F]{1,6})*)[ \t]*\}|([0-9a-fA-F]{4})"
            ).match(s, j + 2)
            if not match:
                self.fail("has an invalid \\u escape", j)
            parts.extend(
                chr(int(code, 16))
                for code in (match.group(1) or match.group(2)).split()
            )
            return match.end()
        if following in "cCM":
            self.fail("has a control or meta escape it can't read", j)
        parts.append(following)
        return j + 2

    def byte(self, code, j):
        # Above 0x7F an escape makes a byte, not a character: the string is
        # binary data, never text.
        if code > 0x7F:
            self.binary = True

    def percent(self):
        s, i = self.s, self.i
        match = re.compile(r"%([qQwWiIrsx]?)([^\w\s])").match(s, i)
        if not match:
            return False
        letter, open_ = match.groups()
        if not letter and open_ in "=":
            # `%=` after a value is an operator; where an argument starts
            # Ruby would read a string, which scripts never write.
            return False
        close = PAIRS.get(open_, open_)
        paired = open_ if open_ in PAIRS else None
        at = match.end()
        if letter in ("w", "W", "i", "I"):
            self.words(i, at, close, paired, letter)
        elif letter == "r":
            self.pattern(at, close, paired)
        else:
            self.quoted(
                i,
                at,
                close,
                paired,
                "single" if letter in ("q", "s") else "double",
                kind={"s": "symbol", "x": "command"}.get(letter),
            )
        return True

    def words(self, start, at, close, open_, letter):
        """A %w list: each word is a literal of its own text only."""
        s = self.s
        mode = "double" if letter in ("W", "I") else "words"
        j, depth = at, 0
        while True:
            while j < self.n and s[j] in SPACE + "\n":
                j += 1
            if j >= self.n:
                self.fail("has a %w list that never closes", start)
            if s[j] == close and depth == 0:
                break
            begin, parts, expressions = j, [], []
            while j < self.n:
                char = s[j]
                if char in SPACE + "\n":
                    break
                if char == close and depth == 0:
                    break
                if open_ is not None and char == open_:
                    depth += 1
                elif open_ is not None and char == close:
                    depth -= 1
                if char == "\\" and j + 1 < self.n:
                    following = s[j + 1]
                    if mode == "words":
                        if following in "\\ \t\n" or following in (close, open_):
                            parts.append(following)
                        elif following == "\r" and s.startswith("\n", j + 2):
                            parts.append("\n")
                            j += 1
                        else:
                            parts.append("\\" + following)
                        j += 2
                        continue
                    if following in " \t":
                        parts.append(following)
                        j += 2
                        continue
                    j = self.escape(j, parts)
                    continue
                if char == "#" and mode == "double" and s.startswith("{", j + 1):
                    self.fail("has interpolation inside a %W list", j)
                parts.append(char)
                j += 1
            literal = self.literal(
                begin,
                j,
                "".join(parts),
                expressions,
                "word",
                protected=letter in ("i", "I"),
            )
            literal["when"] = self.when
        self.i = j + 1
        self.token("string", "", "end")

    def pattern(self, at, close, open_):
        """A regular expression: never text, so only skipped."""
        s = self.s
        j, depth = at, 0
        while j < self.n:
            char = s[j]
            if char == "\\":
                j += 2
                continue
            if char == close and depth == 0:
                break
            if open_ is not None and char == open_:
                depth += 1
            elif open_ is not None and char == close:
                depth -= 1
            if char == "#" and s.startswith("{", j + 1):
                j = self.embedded(j + 2) + 1
                continue
            j += 1
        else:
            self.fail("has a regular expression that never closes", at)
        j += 1
        while j < self.n and s[j] in "imxounse":
            j += 1
        self.i = j
        self.token("regexp", "", "end")

    def heredoc(self):
        s = self.s
        match = HEREDOC.match(s, self.i)
        # class <<self opens a singleton class, not a heredoc.
        if not match or self.tokens and self.tokens[-1]["text"] == "class":
            return False
        flag = match.group(1)
        if flag == "~":
            self.fail("has a <<~ heredoc, which RGSS3 can't run")
        if match.group(4) is not None:
            mode, name = "raw", match.group(4)
        else:
            mode, name = (
                "double",
                next(group for group in match.group(2, 3, 5) if group is not None),
            )
        self.heredocs.append(
            {
                "name": name,
                "indented": flag == "-",
                "mode": mode,
                "command": match.group(5) is not None,
                "when": self.when,
                "token": len(self.tokens),
                "tokens": self.tokens,
            }
        )
        self.i = match.end()
        self.token("string", "", "end")
        return True

    def bodies(self):
        """Reads the bodies of the heredocs opened on the line just ended."""
        s = self.s
        pending, self.heredocs = self.heredocs, []
        for heredoc in pending:
            start = position = self.i
            while True:
                if position >= self.n:
                    self.fail(
                        "has a heredoc " + heredoc["name"] + " that never ends", start
                    )
                end = s.find("\n", position)
                end = self.n if end < 0 else end
                line = s[position:end].removesuffix("\r")
                if (line.lstrip(" \t") if heredoc["indented"] else line) == heredoc[
                    "name"
                ]:
                    break
                position = end + 1
            state, space = self.state, self.space
            if heredoc["mode"] == "raw":
                value = s[start:position].replace("\r\n", "\n")
                expressions = []
            else:
                _, value, expressions = self.text(start, None, None, "double", position)
            self.state, self.space = state, space
            literal = self.literal(
                start,
                position,
                value,
                expressions,
                "heredoc",
                protected=heredoc["command"],
            )
            literal["when"] = heredoc["when"]
            literal["_token"] = heredoc["token"]
            literal["_tokens"] = heredoc["tokens"]
            self.i = self.n if end >= self.n else end + 1

    def character(self):
        """A character literal such as ?a: listed, but one character never
        holds a translation."""
        s, i = self.s, self.i
        if i + 1 >= self.n or s[i + 1] in SPACE + "\n":
            return False
        if s[i + 1] == "\\":
            match = re.compile(
                r"\\(?:u\{[0-9a-fA-F ]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{1,2}|[0-7]{1,3}|[CM]-.|c.|.)"
            ).match(s, i + 1)
            if not match:
                return False
            end = match.end()
        else:
            if (
                (s[i + 1].isalnum() or s[i + 1] == "_")
                and i + 2 < self.n
                and IDENTIFIER_CHAR.match(s, i + 2)
            ):
                return False
            end = i + 2
        parts = []
        if s[i + 1] == "\\":
            self.escape(i + 1, parts)
        else:
            parts.append(s[i + 1])
        self.literal(i, end, "".join(parts), [], "character", protected=True)
        self.i = end
        self.token("string", "", "end")
        return True

    def symbol(self):
        """A symbol where an expression or argument starts; after a value, or
        before a space, a colon is the ternary's."""
        s, i = self.s, self.i
        following = s[i + 1] if i + 1 < self.n else ""
        if self.state == "end" or not following or following in SPACE + "\n#":
            return False
        if following == '"':
            self.quoted(i, i + 2, '"', None, "double", kind="symbol")
            return True
        if following == "'":
            self.quoted(i, i + 2, "'", None, "single", kind="symbol")
            return True
        match = IDENTIFIER.match(s, i + 1)
        if match:
            end = match.end()
            if (
                end < self.n
                and s[end] in "?!="
                and (s[end] != "=" or s[end + 1 : end + 2] not in ("=", "~", ">"))
            ):
                end += 1
            self.i = end
            self.token("value", s[i:end], "end")
            return True
        match = re.compile(r"@@?[A-Za-z_]\w*|\$(?:\w+|.)").match(s, i + 1)
        if match is None:
            match = OPERATOR_NAME.match(s, i + 1)
        if match:
            self.i = match.end()
            self.token("value", s[i : self.i], "end")
            return True
        return False

    # Context

    def context(self):
        """Marks literals whose role keeps them unchanged, as syntax.cjs
        does for JavaScript: hash keys, index lookups, compared values,
        when clauses, loaded files, and strings whose embedded code holds
        Japanese; and those a matcher method takes."""
        # Code holds Latin letters whatever the game's language, so only
        # Japanese embedded in it reads as text the code matches.
        japanese = re.compile(source_pattern("script", JAPANESE))
        for literal in self.literals:
            tokens, position = literal["_tokens"], literal["_token"]
            before = tokens[position - 1] if position > 0 else {}
            after = tokens[position + 1] if position + 1 < len(tokens) else {}
            before_text = before.get("text", "")
            after_text = after.get("text", "")
            call = tokens[position - 2] if position > 1 else {}
            literal["protected"] = bool(
                literal["protected"]
                or literal.pop("when", False)
                or before_text in COMPARISONS
                or after_text in COMPARISONS
                or after_text == "=>"
                or (before_text == "[" and before.get("index"))
                or (before.get("kind") == "ident" and before_text in LOADERS)
                or (
                    before_text == "("
                    and call.get("kind") == "ident"
                    and call.get("text") in LOADERS
                )
                or any(japanese.search(text) for text in literal["expressions"])
            )
            literal["matcher"] = (
                before_text == "("
                and call.get("kind") == "ident"
                and call.get("text") in MATCHERS
            ) or (before.get("kind") == "ident" and before_text in MATCHERS)
