//go:build ignore

// Run from go/: go run lmcc/generate_re2_unicode.go > ../python/lmcc/_re2_unicode.py
// This exports Unicode data, not parser behavior or corpus expectations.
package main

import (
	"encoding/json"
	"fmt"
	"sort"
	"unicode"
)

func main() {
	tables := map[string][][3]uint32{}
	for _, source := range []map[string]*unicode.RangeTable{unicode.Categories, unicode.Scripts} {
		for name, table := range source {
			ranges := [][3]uint32{}
			for _, r := range table.R16 {
				ranges = append(ranges, [3]uint32{uint32(r.Lo), uint32(r.Hi), uint32(r.Stride)})
			}
			for _, r := range table.R32 {
				ranges = append(ranges, [3]uint32{r.Lo, r.Hi, r.Stride})
			}
			tables[name] = ranges
		}
	}
	names := []string{}
	for name := range tables {
		names = append(names, name)
	}
	sort.Strings(names)
	fmt.Printf("\"\"\"RE2 Unicode categories, scripts, and simple-fold cycles.\n\nSource: Go stdlib unicode tables, Unicode %s.\nRegenerate: cd go && go run lmcc/generate_re2_unicode.go > ../python/lmcc/_re2_unicode.py\nData only; generated from Categories, Scripts, and SimpleFold.\n\"\"\"\n\nVERSION = %q\nTABLES = {\n", unicode.Version, unicode.Version)
	for _, name := range names {
		data, _ := json.Marshal(tables[name])
		fmt.Printf("    %q: %s,\n", name, data)
	}
	fmt.Print("}\nFOLDS = [\n    ")
	count := 0
	for r := rune(0); r <= unicode.MaxRune; r++ {
		if f := unicode.SimpleFold(r); f != r {
			fmt.Printf("(%d,%d),", r, f)
			count++
			if count%16 == 0 {
				fmt.Print("\n    ")
			}
		}
	}
	fmt.Print("\n]\n")
}
