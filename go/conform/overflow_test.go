package conform

import (
	"strings"
	"testing"
)

func TestScaledNumberOverflowIsFormatReadError(t *testing.T) {
	for _, text := range []string{"1e400", "-1e400"} {
		fixture := `{
          "kind":"refuse", "vocab":["std"],
          "entry":{"name":"overflow","versions":{"kernel":"0.2.0","vocab":{}},"template":[{"role":"system","text":"<n>{n}</n>"}],
                   "parse":{"kind":"derived"},"formats":{"number":{"use":"scaled_number"}}},
          "signature":{"instructions":"","fields":[{"name":"n","direction":"output","shape":{"type":"number"}}]},
          "response":"<n>NUMBER</n>","expect":{"code":"format-read-error","at":"parse"}}
        `
		if ok, detail := RunLine(strings.ReplaceAll(fixture, "NUMBER", text)); !ok {
			t.Fatal(detail)
		}
	}
}
