// Package lmccstd is the standard vocabulary pack, registered through the
// kernel's sockets exactly like anyone else's. Behavior is legislated in
// contract/spec/vocab/ and pinned by the corpus.
package lmccstd

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"

	"lmcc/lmcc"
)

const Version = "0.1.0"

// The std formats implement lmcc.Format. `base` supplies the defaults.

type base struct{ name string }

func (b base) Name() string      { return b.name }
func (b base) Direction() string { return "both" }
func (b base) Emits() string     { return "text" }
func (b base) RoundTrip() bool   { return true }
func (b base) Reads() []string   { return []string{"text"} }

// ------------------------------------------------------------ format/json

var fenceRE = regexp.MustCompile(
	`(?s)^[ \t\n\r\f\v]*` + "```" + `[a-zA-Z0-9_-]*[ \t\n\r\f\v]*\n(.*?)\n?[ \t\n\r\f\v]*` + "```" + `[ \t\n\r\f\v]*$`)

type JSONFormat struct {
	base
	indent int
}

func newJSONFormat(options *lmcc.Object) (lmcc.Format, error) {
	c := &JSONFormat{base: base{"json"}, indent: 2}
	if v, ok := options.Get("indent"); ok {
		switch n := v.(type) {
		case nil:
			c.indent = -1
		case int64:
			c.indent = int(n)
		case float64:
			c.indent = int(n)
		default:
			return nil, fmt.Errorf("json codec: indent must be an integer or null")
		}
	}
	return c, nil
}

func (c *JSONFormat) Accepts() []string { return []string{"*"} }

func (c *JSONFormat) Describe(f *lmcc.Field) string {
	return "JSON matching this schema: " + lmcc.MarshalJSON(f.Shape, -1)
}

func (c *JSONFormat) Write(value any, f *lmcc.Field) (any, error) {
	return lmcc.MarshalJSON(value, c.indent), nil
}

func (c *JSONFormat) Read(span lmcc.Span, f *lmcc.Field) (any, error) {
	text := span.Text()
	if m := fenceRE.FindStringSubmatch(text); m != nil {
		text = m[1]
	}
	return lmcc.ParseJSON(text)
}

// ----------------------------------------------------------- format/table

type TableFormat struct {
	base
	columns   []string
	delimiter string
	escape    string
	null      string
}

func newTableFormat(options *lmcc.Object) (lmcc.Format, error) {
	cols := options.List("columns")
	if cols == nil {
		return nil, fmt.Errorf("table codec requires the 'columns' option")
	}
	c := &TableFormat{base: base{"table"}, delimiter: "|", escape: "\\", null: ""}
	for _, col := range cols {
		s, ok := col.(string)
		if !ok {
			return nil, fmt.Errorf("table codec: columns must be strings")
		}
		c.columns = append(c.columns, s)
	}
	if v, ok := options.Str("delimiter"); ok {
		c.delimiter = v
	}
	if v, ok := options.Str("escape"); ok {
		c.escape = v
	}
	if v, ok := options.Str("null"); ok {
		c.null = v
	}
	return c, nil
}

func (c *TableFormat) Accepts() []string { return []string{"list[object]", "list[*]"} }

func (c *TableFormat) row(cells []string) string {
	d := c.delimiter
	return d + " " + strings.Join(cells, " "+d+" ") + " " + d
}

func (c *TableFormat) Describe(f *lmcc.Field) string {
	return c.row(c.columns) + "  (one row per item)"
}

func (c *TableFormat) Write(value any, f *lmcc.Field) (any, error) {
	items, ok := value.([]any)
	if !ok {
		return "", fmt.Errorf("table codec spells a list of objects, got %T", value)
	}
	var rows []string
	for _, item := range items {
		obj, ok := item.(*lmcc.Object)
		if !ok {
			return "", fmt.Errorf("table codec: each item must be an object, got %T", item)
		}
		var cells []string
		for _, col := range c.columns {
			v, _ := obj.Get(col)
			cell, err := c.spell(v, col)
			if err != nil {
				return "", err
			}
			cell = strings.ReplaceAll(cell, c.escape, c.escape+c.escape)
			cell = strings.ReplaceAll(cell, c.delimiter, c.escape+c.delimiter)
			cells = append(cells, cell)
		}
		rows = append(rows, c.row(cells))
	}
	return strings.Join(rows, "\n"), nil
}

func (c *TableFormat) spell(v any, col string) (string, error) {
	switch x := v.(type) {
	case nil:
		return c.null, nil
	case string:
		return x, nil
	case bool:
		if x {
			return "true", nil
		}
		return "false", nil
	case int64:
		return strconv.FormatInt(x, 10), nil
	case float64:
		return lmcc.FormatNumber(x), nil
	}
	return "", fmt.Errorf("column %q: %T is not a cell value", col, v)
}

func (c *TableFormat) Read(span lmcc.Span, f *lmcc.Field) (any, error) {
	var props *lmcc.Object
	if items := f.Shape.Object("items"); items != nil {
		props = items.Object("properties")
	}
	out := []any{}
	for _, line := range strings.Split(span.Text(), "\n") {
		line = lmcc.Strip(line)
		if !strings.HasPrefix(line, c.delimiter) {
			continue
		}
		cells := c.split(line)
		if c.isHeader(cells) {
			continue
		}
		if len(cells) != len(c.columns) {
			return nil, fmt.Errorf("row has %d cells, expected %d (%v): %q", len(cells), len(c.columns), c.columns, line)
		}
		item := lmcc.NewObject()
		for i, col := range c.columns {
			cell := lmcc.Strip(cells[i])
			if cell == c.null {
				item.Set(col, nil)
				continue
			}
			prop := lmcc.NewObject()
			if props != nil {
				if p := props.Object(col); p != nil {
					prop = p
				}
			}
			v, err := readCell(prop, cell, "column '"+col+"'")
			if err != nil {
				return nil, err
			}
			item.Set(col, v)
		}
		out = append(out, item)
	}
	return out, nil
}

func (c *TableFormat) isHeader(cells []string) bool {
	if len(cells) != len(c.columns) {
		return false
	}
	for i, cell := range cells {
		if lmcc.Strip(cell) != c.columns[i] {
			return false
		}
	}
	return true
}

func (c *TableFormat) split(line string) []string {
	inner := line[len(c.delimiter):]
	inner = strings.TrimSuffix(inner, c.delimiter)
	var cells []string
	var cur strings.Builder
	for i := 0; i < len(inner); {
		if c.escape != "" && strings.HasPrefix(inner[i:], c.escape) && i+len(c.escape) < len(inner) {
			// the escaped character is one rune
			j := i + len(c.escape)
			_, size := decodeRune(inner[j:])
			cur.WriteString(inner[j : j+size])
			i = j + size
			continue
		}
		if strings.HasPrefix(inner[i:], c.delimiter) {
			cells = append(cells, cur.String())
			cur.Reset()
			i += len(c.delimiter)
			continue
		}
		_, size := decodeRune(inner[i:])
		cur.WriteString(inner[i : i+size])
		i += size
	}
	cells = append(cells, cur.String())
	return cells
}

func decodeRune(s string) (rune, int) {
	for _, r := range s {
		return r, len(string(r))
	}
	return 0, 1
}

// readCell applies the kernel scalar rules and surfaces refusals as
// codec errors, which is the spec's word for a bad cell.
func readCell(shape *lmcc.Object, text, where string) (v any, err error) {
	defer func() {
		if r := recover(); r != nil {
			if e, ok := r.(*lmcc.Error); ok {
				err = fmt.Errorf("%s", e.Detail)
				return
			}
			panic(r)
		}
	}()
	return lmcc.ReadValue(shape, text, where), nil
}

// --------------------------------------------------- format/scaled_number

type ScaledNumberFormat struct {
	base
	scale  float64
	suffix string
	round  *int
}

func newScaledNumberFormat(options *lmcc.Object) (lmcc.Format, error) {
	c := &ScaledNumberFormat{base: base{"scaled_number"}, scale: 1}
	if v, ok := options.Get("scale"); ok {
		switch n := v.(type) {
		case int64:
			c.scale = float64(n)
		case float64:
			c.scale = n
		default:
			return nil, fmt.Errorf("scaled_number: scale must be a number")
		}
	}
	if v, ok := options.Str("suffix"); ok {
		c.suffix = v
	}
	if v, ok := options.Get("round"); ok && v != nil {
		var n int
		switch x := v.(type) {
		case int64:
			n = int(x)
		case float64:
			n = int(x)
		default:
			return nil, fmt.Errorf("scaled_number: round must be an integer or null")
		}
		c.round = &n
	}
	return c, nil
}

func (c *ScaledNumberFormat) Accepts() []string { return []string{"number", "integer"} }

func (c *ScaledNumberFormat) Describe(f *lmcc.Field) string {
	example := "0.83"
	if c.scale == 100 {
		example = "83"
	}
	return "a number like " + example + c.suffix
}

func (c *ScaledNumberFormat) Write(value any, _ *lmcc.Field) (any, error) {
	var n float64
	switch x := value.(type) {
	case int64:
		n = float64(x)
	case float64:
		n = x
	default:
		return "", fmt.Errorf("scaled_number spells numbers, got %T", value)
	}
	scaled := n * c.scale
	if c.round != nil {
		scaled = lmcc.RoundHalfEven(scaled, *c.round)
	}
	return lmcc.FormatNumber(scaled) + c.suffix, nil
}

func (c *ScaledNumberFormat) Read(span lmcc.Span, f *lmcc.Field) (any, error) {
	t := lmcc.Strip(span.Text())
	if c.suffix != "" {
		t = strings.TrimSuffix(t, c.suffix)
	}
	v, err := readCell(lmcc.Obj("type", "number"), t, "scaled_number")
	if err != nil {
		return nil, err
	}
	return v.(float64) / c.scale, nil
}
