"""RE2 admission and matching, independent of Python's host syntax."""
import pytest

from lmcc import Refusal
from lmcc.parse import _text_spans
from lmcc.strategy import check_re2


@pytest.mark.parametrize("pattern,text,want", [
    (r"\w+", "héllo", ["h", "llo"]),
    (r"[\w]+", "héllo", ["h", "llo"]),
    (r"\d+", "٣12", ["12"]),
    (r"\s+", "\v\t\n\f\r \u00a0", ["\t\n\f\r "]),
    (r"[\s]+", "\v\t\n\f\r \u00a0", ["\t\n\f\r "]),
    (r"\W+", "é_", ["é"]),
    (r"[\D]+", "٣12", ["٣"]),
    (r"\S+", "\v \u00a0", ["\v", "\u00a0"]),
    (r"\b.\b", "éaé", ["a"]),
    (r"\B.\B", "éaé", []),
    (r"\Q(?=a)++\E", "(?=a)++", ["(?=a)++"]),
    (r"\Q.+", ".+", [".+"]),
    (r"[[:alpha:]]+", "héllo", ["h", "llo"]),
    (r"[[:^alpha:]]+", "héllo!", ["é", "!"]),
    (r"[[:space:]]+", "\v\t \u00a0", ["\v\t "]),
    (r"[[:punct:]]+", "az!@[{}]`~09", ["!@[{}]`~"]),
    (r"\p{L}+", "héllo٣", ["héllo"]),
    (r"[\pL]+", "héllo٣", ["héllo"]),
    (r"\P{L}+", "héllo٣", ["٣"]),
    (r"\p{^L}+", "héllo٣", ["٣"]),
    (r"\p{Greek}+", "aαβb", ["αβ"]),
    (r"\p{Any}+", "a\n😀", ["a\n😀"]),
    (r"(?i)k", "KkK", ["K", "k", "K"]),
    (r"(?i)i", "Iiİı", ["I", "i"]),
    (r"(?i)\w+", "İıſK", ["ſK"]),
    (r"(?i)\W+", "İıſK", ["İı"]),
    (r"(?i)\b(k)\b", "K K", ["K"]),
    (r"(?i:k)(?-i:k)", "Kk", ["Kk"]),
    (r"(?i)\Qk\E", "K", ["K"]),
    (r"a(?i)b", "aB", ["aB"]),
    (r"a$", "a\n", []),
    (r"(?m)^a$", "b\na\nb", ["a"]),
    (r"\Aa\z", "a\n", []),
    (r".", "\n\r\u2028\u2029", ["\n", "\r", "\u2028", "\u2029"]),
    (r"(?-s:.)", "\n\r\u2028\u2029", ["\r", "\u2028", "\u2029"]),
    (r"(?U)a.+b", "a1b2b", ["a1b"]),
    (r"(?U)a.+?b", "a1b2b", ["a1b2b"]),
    (r"\x{1F600}\141\12", "😀a\n", ["😀a\n"]),
    (r"[\x{1F600}-\x{1F601}]", "😀😁😂", ["😀", "😁"]),
    (r"[+?}]+", "+?}", ["+?}"]),
    (r"[]a-]+", "]a-", ["]a-"]),
    (r"a*?", "a", []),
    (r"DROP:()", "DROP:", [""]),
    (r"(a|)*", "aa", ["a"]),
    (r"(a*)+", "aa", ["aa"]),
    (r"X((a*)*)Y", "XaaY", ["aa"]),
    (r"X((a*)*)Y", "XY", [""]),
    (r"(a|ab)", "ab", ["a"]),
    (r"(ab|a)", "ab", ["ab"]),
    (r"^*a$+", "a", ["a"]),
    (r"{01}", "{01}", ["{01}"]),
])
def test_re2_matching(pattern, text, want):
    check_re2(pattern, where="test")
    assert [s[2] for s in _text_spans(text, {"pattern": pattern})] == want


@pytest.mark.parametrize("pattern", [
    r"(?=a)", r"(?!a)", r"(?<=a)", r"(?<!a)", r"(?>a)",
    r"(?P<x>a)", r"(?<x>a)", r"(a)\1", r"\k<x>",
    r"a++", r"a*+", r"a?+", r"a{2}+", r"a{1,2}+",
    r"\p{L}++", r"[[:alpha:]]++", r"\Q+\E++",
    r"\p{Missing}", r"[[:missing:]]", r"(?x)a", r"(?a)a", r"(?u)a",
    r"\u0061", r"\Z", r"[\b]", r"a{1001}", r"(a{500}){3}",
    r"[z-a]", r"[", r"(", r"a)",
])
def test_re2_refuses_outside_dialect(pattern):
    with pytest.raises(Refusal) as err:
        check_re2(pattern, where="test")
    assert err.value.code == "entry-malformed"
    assert err.value.fix == {"action": "edit-entry", "path": "test"}


def test_nested_repetition_search_work_is_linear(monkeypatch):
    from lmcc.re2 import compile
    pattern = compile("(a+)+b")
    original = pattern.closure
    calls = 0

    def counted(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(pattern, "closure", counted)
    for size in (1000, 2000):
        calls = 0
        assert pattern.search("a" * size) is None
        assert calls <= 4 * size + 1
