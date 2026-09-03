// lmcc-conform is the corpus driver for the Go implementation: it speaks
// the JSON Lines protocol of contract/spec/kernel.md §10.
//
//	contract/harness/runner.py --driver 'go run ./cmd/lmcc-conform' --cwd go
//
// One case object per line in, one {"ok", "detail"} per line out. The
// driver builds an empty registry per case (plus the packs the case
// names in "vocab"), runs the case's kind, and compares.
package main

import (
	"bufio"
	"fmt"
	"os"

	"lmcc/conform"
	"lmcc/lmcc"
)

func main() {
	in := bufio.NewScanner(os.Stdin)
	in.Buffer(make([]byte, 1<<20), 1<<26)
	out := bufio.NewWriter(os.Stdout)
	defer out.Flush()
	for in.Scan() {
		line := in.Text()
		if line == "" {
			continue
		}
		ok, detail := conform.RunLine(line)
		fmt.Fprintln(out, lmcc.MarshalJSON(lmcc.Obj("ok", ok, "detail", detail), -1))
		out.Flush()
	}
}
