package lmcc

// Kernel §7a: the text rules every implementation shares. Nothing in the
// kernel or in vocabulary may call strings.TrimSpace, strconv.Atoi or
// ParseFloat on model text directly; these are the only doors.

import (
	"math"
	"regexp"
	"strconv"
	"strings"
)

const whitespace = " \t\n\r\f\v"

var (
	identifierRE = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)
	integerRE    = regexp.MustCompile(`^-?[0-9]+$`)
	numberRE     = regexp.MustCompile(`^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$`)
)

// Strip trims the six ASCII whitespace characters, nothing else.
func Strip(s string) string { return strings.Trim(s, whitespace) }

func RStrip(s string) string { return strings.TrimRight(s, whitespace) }

func IsIdentifier(s string) bool { return identifierRE.MatchString(s) }

// FormatNumber is ECMAScript Number::toString over the shortest
// round-trip digits: 3 for 3.0, 1e+21, 1e-7, 0.000001, 0 for -0.
func FormatNumber(f float64) string {
	if math.IsNaN(f) || math.IsInf(f, 0) {
		refusef("value-invalid", "%v has no portable number spelling", f)
	}
	if f == 0 {
		return "0"
	}
	sign := ""
	if f < 0 {
		sign = "-"
		f = -f
	}
	e := strconv.FormatFloat(f, 'e', -1, 64) // d.dddde±XX, shortest
	mant, expS, _ := strings.Cut(e, "e")
	exp, _ := strconv.Atoi(expS)
	digits := strings.Replace(mant, ".", "", 1)
	digits = strings.TrimRight(digits, "0")
	if digits == "" {
		digits = "0"
	}
	k := len(digits)
	n := exp + 1 // value = 0.d1..dk × 10^n
	var body string
	switch {
	case k <= n && n <= 21:
		body = digits + strings.Repeat("0", n-k)
	case 0 < n && n <= 21:
		body = digits[:n] + "." + digits[n:]
	case -6 < n && n <= 0:
		body = "0." + strings.Repeat("0", -n) + digits
	default:
		ex := n - 1
		m := digits
		if k > 1 {
			m = digits[:1] + "." + digits[1:]
		}
		s := "+"
		if ex < 0 {
			s = "-"
			ex = -ex
		}
		body = m + "e" + s + strconv.Itoa(ex)
	}
	return sign + body
}

func ReadInteger(text, where string) int64 {
	t := Strip(text)
	if !integerRE.MatchString(t) {
		refusef("value-invalid", "%s: %q is not an integer", where, t)
	}
	n, err := strconv.ParseInt(t, 10, 64)
	if err != nil {
		refusef("value-invalid", "%s: %q is outside the int64 range", where, t)
	}
	return n
}

func ReadNumber(text, where string) float64 {
	t := Strip(text)
	if !numberRE.MatchString(t) {
		refusef("value-invalid", "%s: %q is not a number", where, t)
	}
	f, err := strconv.ParseFloat(t, 64)
	if err != nil || math.IsInf(f, 0) {
		refusef("value-invalid", "%s: %q is not a finite number", where, t)
	}
	return f
}

func ReadBoolean(text, where string) bool {
	t := Strip(text)
	low := asciiLower(t)
	switch low {
	case "true", "yes":
		return true
	case "false", "no":
		return false
	}
	refusef("value-invalid", "%s: %q is not a boolean", where, t)
	return false
}

func asciiLower(s string) string {
	b := []byte(s)
	for i, c := range b {
		if c >= 'A' && c <= 'Z' {
			b[i] = c + 32
		}
	}
	return string(b)
}

// RoundHalfEven is the kernel rounding rule: roundeven(x × 10^n) / 10^n
// in binary64.
func RoundHalfEven(x float64, places int) float64 {
	p := math.Pow(10, float64(places))
	return math.RoundToEven(x*p) / p
}
