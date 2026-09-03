package conform

import (
	"os"
	"path/filepath"
	"sort"
	"testing"
)

// TestCorpus runs every corpus case in-process. The corpus is the
// authority: a failure here is a contract failure, never a test bug.
func TestCorpus(t *testing.T) {
	files, err := filepath.Glob(filepath.Join("..", "..", "contract", "corpus", "cases", "*.json"))
	if err != nil || len(files) == 0 {
		t.Fatalf("no corpus cases found: %v", err)
	}
	sort.Strings(files)
	for _, f := range files {
		data, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		name := filepath.Base(f)
		t.Run(name, func(t *testing.T) {
			o := RunLineOutcome(string(data))
			if o.Unclaimed != "" {
				t.Skipf("unclaimed: %s", o.Unclaimed)
			}
			if !o.OK {
				t.Errorf("%s\n%s", name, o.Detail)
			}
		})
	}
}
