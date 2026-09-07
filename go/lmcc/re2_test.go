package lmcc

import (
	"os"
	"strings"
	"testing"
	"unicode"
)

func TestRE2UnicodeDataVersion(t *testing.T) {
	data, err := os.ReadFile("../../python/lmcc/_re2_unicode.py")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), `VERSION = "`+unicode.Version+`"`) {
		t.Fatal("review and regenerate Python RE2 Unicode data after a Go Unicode upgrade")
	}
}

func TestRE2Matching(t *testing.T) {
	cases := []struct {
		pattern, text string
		want          []string
	}{
		{`\w+`, "héllo", []string{"h", "llo"}},
		{`[\w]+`, "héllo", []string{"h", "llo"}},
		{`\d+`, "٣12", []string{"12"}},
		{`\s+`, "\v\t\n\f\r \u00a0", []string{"\t\n\f\r "}},
		{`[\s]+`, "\v\t\n\f\r \u00a0", []string{"\t\n\f\r "}},
		{`\W+`, "é_", []string{"é"}},
		{`[\D]+`, "٣12", []string{"٣"}},
		{`\S+`, "\v \u00a0", []string{"\v", "\u00a0"}},
		{`\b.\b`, "éaé", []string{"a"}},
		{`\B.\B`, "éaé", []string{}},
		{`\Q(?=a)++\E`, "(?=a)++", []string{"(?=a)++"}},
		{`\Q.+`, ".+", []string{".+"}},
		{`[[:alpha:]]+`, "héllo", []string{"h", "llo"}},
		{`[[:^alpha:]]+`, "héllo!", []string{"é", "!"}},
		{`[[:space:]]+`, "\v\t \u00a0", []string{"\v\t "}},
		{`[[:punct:]]+`, "az!@[{}]`~09", []string{"!@[{}]`~"}},
		{`\p{L}+`, "héllo٣", []string{"héllo"}},
		{`[\pL]+`, "héllo٣", []string{"héllo"}},
		{`\P{L}+`, "héllo٣", []string{"٣"}},
		{`\p{^L}+`, "héllo٣", []string{"٣"}},
		{`\p{Greek}+`, "aαβb", []string{"αβ"}},
		{`\p{Any}+`, "a\n😀", []string{"a\n😀"}},
		{`(?i)k`, "KkK", []string{"K", "k", "K"}},
		{`(?i)i`, "Iiİı", []string{"I", "i"}},
		{`(?i)\w+`, "İıſK", []string{"ſK"}},
		{`(?i)\W+`, "İıſK", []string{"İı"}},
		{`(?i)\b(k)\b`, "K K", []string{"K"}},
		{`(?i:k)(?-i:k)`, "Kk", []string{"Kk"}},
		{`(?i)\Qk\E`, "K", []string{"K"}},
		{`a(?i)b`, "aB", []string{"aB"}},
		{`a$`, "a\n", []string{}},
		{`(?m)^a$`, "b\na\nb", []string{"a"}},
		{`\Aa\z`, "a\n", []string{}},
		{`.`, "\n\r\u2028\u2029", []string{"\n", "\r", "\u2028", "\u2029"}},
		{`(?-s:.)`, "\n\r\u2028\u2029", []string{"\r", "\u2028", "\u2029"}},
		{`(?U)a.+b`, "a1b2b", []string{"a1b"}},
		{`(?U)a.+?b`, "a1b2b", []string{"a1b2b"}},
		{`\x{1F600}\141\12`, "😀a\n", []string{"😀a\n"}},
		{`[\x{1F600}-\x{1F601}]`, "😀😁😂", []string{"😀", "😁"}},
		{`[+?}]+`, "+?}", []string{"+?}"}},
		{`[]a-]+`, "]a-", []string{"]a-"}},
		{`a*?`, "a", []string{}},
		{`DROP:()`, "DROP:", []string{""}},
		{`(a|)*`, "aa", []string{"a"}},
		{`(a*)+`, "aa", []string{"aa"}},
		{`X((a*)*)Y`, "XaaY", []string{"aa"}},
		{`X((a*)*)Y`, "XY", []string{""}},
		{`(a|ab)`, "ab", []string{"a"}},
		{`(ab|a)`, "ab", []string{"ab"}},
		{`^*a$+`, "a", []string{"a"}},
		{`{01}`, "{01}", []string{"{01}"}},
	}
	for _, tc := range cases {
		t.Run(tc.pattern, func(t *testing.T) {
			if err := try(func() { checkRE2(tc.pattern, "test") }); err != nil {
				t.Fatal(err)
			}
			spans := textSpans(tc.text, Obj("pattern", tc.pattern))
			if len(spans) != len(tc.want) {
				t.Fatalf("got %v, want %v", spans, tc.want)
			}
			for i, s := range spans {
				if s.capture != tc.want[i] {
					t.Fatalf("got %q, want %q", s.capture, tc.want[i])
				}
			}
		})
	}
}

func TestRE2Admission(t *testing.T) {
	for _, pattern := range []string{
		`(?=a)`, `(?!a)`, `(?<=a)`, `(?<!a)`, `(?>a)`, `(?P<x>a)`, `(?<x>a)`, `(a)\1`, `\k<x>`,
		`a++`, `a*+`, `a?+`, `a{2}+`, `a{1,2}+`, `\p{L}++`, `[[:alpha:]]++`, `\Q+\E++`,
		`\p{Missing}`, `[[:missing:]]`, `(?x)a`, `(?a)a`, `(?u)a`, `\u0061`, `\Z`, `[\b]`,
		`a{1001}`, `(a{500}){3}`, `[z-a]`, `[`, `(`, `a)`,
	} {
		e := try(func() { checkRE2(pattern, "test") })
		if e == nil || e.Code != "entry-malformed" || !Equal(e.Fix, fixEditEntry("test")) {
			t.Errorf("%s: %v", pattern, e)
		}
	}
}
