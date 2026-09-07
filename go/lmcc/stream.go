package lmcc

// Incremental, sans-I/O parsing (kernel §8). This reducer is not a second
// parser. Every Feed does work proportional to the delta, never to the
// reply: markers are found by incremental scanners over a small overlap
// window, and each field keeps only the text it already emitted plus a
// short held tail (outer whitespace and any suffix that can still grow
// into a marker). Finish delegates final structure and typed reads to
// Plan.parseWithSpans, then proves the projection agrees with batch.
//
// Hazard rule. A marker occurrence acts — opens a field's section, ends
// the previous one, or fixes a close — only once no boundary marker can
// still be growing across it. Otherwise a marker learned later could
// start inside an earlier one and shrink a section whose text was
// already emitted, which the hold-back law forbids. The check is exact:
// it costs nothing for templates whose markers cannot overlap.

import (
	"errors"
	"sort"
	"strings"
)

// StreamResult carries events caused by EOF and the final typed values.
type StreamResult struct {
	Events []any
	Values *Object
}

// ------------------------------------------------------------ primitives

// prefixTable holds every proper prefix of a marker set: "can this suffix
// still grow into a marker?" answered in O(longest marker).
type prefixTable struct {
	table   map[string]bool
	longest int
}

func newPrefixTable(markers []string) *prefixTable {
	t := &prefixTable{table: map[string]bool{}}
	for _, m := range markers {
		for n := 1; n < len(m); n++ {
			t.table[m[:n]] = true
		}
		if len(m)-1 > t.longest {
			t.longest = len(m) - 1
		}
	}
	return t
}

// hold is the length of the longest suffix of text that is a proper
// prefix of some marker (kernel §8 hold-back).
func (t *prefixTable) hold(text string) int {
	n := t.longest
	if len(text) < n {
		n = len(text)
	}
	for ; n > 0; n-- {
		if t.table[text[len(text)-n:]] {
			return n
		}
	}
	return 0
}

// growsBetween: does any suffix of the text (whose last len(window) bytes
// are window and which ends at absolute end) that can still grow into a
// marker start strictly between absolute lo and hi?
func (t *prefixTable) growsBetween(window string, end, lo, hi int) bool {
	first := end - hi + 1
	if first < 1 {
		first = 1
	}
	last := t.longest
	if len(window) < last {
		last = len(window)
	}
	if end-lo-1 < last {
		last = end - lo - 1
	}
	for n := first; n <= last; n++ {
		if t.table[window[len(window)-n:]] {
			return true
		}
	}
	return false
}

// scanner reports non-overlapping occurrences of one marker (strings.Count
// order) by absolute start as soon as each is complete.
type scanner struct {
	marker  string
	end     int    // absolute position up to which text was seen
	pending string // unresolved suffix (shorter than the marker)
}

func newScanner(marker string, start int) *scanner {
	return &scanner{marker: marker, end: start}
}

func (s *scanner) feed(text string) []int {
	if text == "" || s.marker == "" {
		s.end += len(text)
		return nil
	}
	buf := s.pending + text
	base := s.end - len(s.pending)
	var found []int
	i := 0
	for {
		j := strings.Index(buf[i:], s.marker)
		if j < 0 {
			break
		}
		j += i
		found = append(found, base+j)
		i = j + len(s.marker)
	}
	s.end += len(text)
	keep := len(buf) - (len(s.marker) - 1)
	if i > keep {
		keep = i
	}
	s.pending = buf[keep:]
	return found
}

// streamField is per-field emission state shared by every projection kind.
type streamField struct {
	name       string
	present    bool
	started    bool
	emitted    []string
	hasEmitted bool
	pending    []string
}

func (f *streamField) emit(text string) {
	if text != "" {
		f.emitted = append(f.emitted, text)
		f.hasEmitted = true
		f.pending = append(f.pending, text)
	}
}

func (f *streamField) emittedText() string { return strings.Join(f.emitted, "") }

// -------------------------------------------------------------- routings
//
// Each routing is a transducer: it receives the text delta left by the
// previous stage and returns the stable text it passes on.

type textStage interface {
	feed(delta string, final bool) string
	captured() []string
}

type betweenStage struct {
	open, close string
	consume     bool
	hold        *prefixTable
	buf         string
	inside      bool
	captures    []string
}

func newBetweenStage(r *Object) *betweenStage {
	pair := r.List("between")
	open, close := pair[0].(string), pair[1].(string)
	return &betweenStage{open: open, close: close, consume: r.Bool("consume", false),
		hold: newPrefixTable([]string{open})}
}

func (s *betweenStage) captured() []string { return s.captures }

func (s *betweenStage) feed(delta string, final bool) string {
	var out []string
	if !s.consume {
		out = append(out, delta)
	}
	buf := s.buf + delta
	for {
		if !s.inside {
			i := strings.Index(buf, s.open)
			if i < 0 {
				if s.consume {
					keep := 0
					if !final {
						keep = s.hold.hold(buf)
					}
					out = append(out, buf[:len(buf)-keep])
					buf = buf[len(buf)-keep:]
				} else {
					keep := len(s.open) - 1
					if keep < 0 {
						keep = 0
					}
					if len(buf) < keep {
						keep = len(buf)
					}
					buf = buf[len(buf)-keep:]
				}
				break
			}
			if s.consume {
				out = append(out, buf[:i])
			}
			buf = buf[i:]
			s.inside = true
		}
		j := strings.Index(buf[len(s.open):], s.close)
		if j < 0 {
			if final && s.consume {
				out = append(out, buf) // batch ignores an unclosed extractor
				buf = ""
			}
			break
		}
		j += len(s.open)
		s.captures = append(s.captures, Strip(buf[len(s.open):j]))
		buf = buf[j+len(s.close):]
		s.inside = false
		if s.open == "" && s.close == "" {
			break // batch loops forever here; do not hang the reducer too
		}
	}
	s.buf = buf
	return strings.Join(out, "")
}

type lineStage struct {
	prefix   string
	consume  bool
	line     string
	captures []string
}

func newLineStage(r *Object) *lineStage {
	prefix, _ := r.Str("line_prefixed")
	return &lineStage{prefix: prefix, consume: r.Bool("consume", false)}
}

func (s *lineStage) captured() []string { return s.captures }

func (s *lineStage) feed(delta string, final bool) string {
	var out []string
	if !s.consume {
		out = append(out, delta)
	}
	lines := strings.Split(s.line+delta, "\n")
	last := lines[len(lines)-1]
	for _, line := range lines[:len(lines)-1] {
		if strings.HasPrefix(line, s.prefix) {
			s.captures = append(s.captures, Strip(line[len(s.prefix):]))
			if s.consume {
				out = append(out, "\n")
			}
		} else if s.consume {
			out = append(out, line+"\n")
		}
	}
	if final {
		if strings.HasPrefix(last, s.prefix) {
			s.captures = append(s.captures, Strip(last[len(s.prefix):]))
		} else if s.consume {
			out = append(out, last)
		}
		last = ""
	}
	s.line = last
	return strings.Join(out, "")
}

// patternStage: a regex needs the whole text; later bytes can change any match.
type patternStage struct {
	spec     *Object
	consume  bool
	pieces   strings.Builder
	captures []string
}

func newPatternStage(r *Object) *patternStage {
	return &patternStage{spec: r, consume: r.Bool("consume", false)}
}

func (s *patternStage) captured() []string { return s.captures }

func (s *patternStage) feed(delta string, final bool) string {
	s.pieces.WriteString(delta)
	if !final {
		if s.consume {
			return ""
		}
		return delta
	}
	text := s.pieces.String()
	spans := textSpans(text, s.spec)
	s.captures = make([]string, 0, len(spans))
	for _, span := range spans {
		s.captures = append(s.captures, Strip(span.capture))
	}
	if !s.consume {
		return ""
	}
	if len(spans) == 0 {
		return text
	}
	var b strings.Builder
	pos := 0
	for _, span := range spans {
		b.WriteString(text[pos:span.start])
		pos = span.end
	}
	b.WriteString(text[pos:])
	return b.String()
}

// channelStage: text of every part of one kind, each stripped, joined by newlines.
type channelStage struct {
	kind       string
	texts      []*strings.Builder // one per text-bearing matching part
	anyPart    bool
	held       string
	hasEmitted bool
}

func (s *channelStage) captured() []string {
	out := make([]string, 0, len(s.texts))
	for _, b := range s.texts {
		out = append(out, Strip(b.String()))
	}
	return out
}

// part: a part delta arrived; returns this routing's stable raw delta.
func (s *channelStage) part(kind string, text *string, newPart bool) string {
	if kind != s.kind {
		return ""
	}
	s.anyPart = true
	if text == nil {
		return ""
	}
	out := ""
	if newPart {
		s.texts = append(s.texts, &strings.Builder{})
		s.held = ""
		s.hasEmitted = false
		if len(s.texts) > 1 {
			out = "\n"
		}
	}
	s.texts[len(s.texts)-1].WriteString(*text)
	candidate := s.held + *text
	if !s.hasEmitted {
		candidate = strings.TrimLeft(candidate, whitespace)
	}
	stable := strings.TrimRight(candidate, whitespace)
	s.held = candidate[len(stable):]
	if stable != "" {
		s.hasEmitted = true
	}
	return out + stable
}

// ---------------------------------------------------------- derived lens

// section is one field's section of the lens text (kernel §4 read backwards).
type section struct {
	field       *streamField
	start       int
	after       int
	close       string
	scanner     *scanner
	closeStarts []int
	end         int // -1 while open
	received    int // absolute position up to which held reaches
	held        string
	fixed       *string
	hold        *prefixTable // boundary markers + own close
}

// cut is the held text up to absolute limit; drops the rest.
func (s *section) cut(limit int) string {
	if limit >= s.received {
		return s.held
	}
	drop := s.received - limit
	if drop > len(s.held) {
		if s.field.hasEmitted {
			panic("stream projection for " + s.field.name + " revised emitted text")
		}
		return ""
	}
	return s.held[:len(s.held)-drop]
}

// advance emits the stable prefix of the held text (up to limit, or all if limit < 0).
func (s *section) advance(limit int) {
	candidate, rest := s.held, ""
	if limit >= 0 {
		candidate = s.cut(limit)
		rest = s.held[len(candidate):]
	}
	if !s.field.hasEmitted {
		candidate = strings.TrimLeft(candidate, whitespace)
	}
	n := s.hold.hold(candidate)
	stable := strings.TrimRight(candidate[:len(candidate)-n], whitespace)
	s.field.emit(stable)
	s.held = candidate[len(stable):] + rest
}

// fix: the section is final up to limit; release everything.
func (s *section) fix(limit int) {
	candidate := s.cut(limit)
	if !s.field.hasEmitted {
		candidate = strings.TrimLeft(candidate, whitespace)
	}
	s.field.emit(strings.TrimRight(candidate, whitespace))
	raw := s.field.emittedText()
	s.fixed = &raw
	s.held = ""
}

type wantedAnchor struct{ name, marker, close string }

type derivedReducer struct {
	fields     map[string]*streamField
	wanted     []wantedAnchor
	tail       string
	bounds     *prefixTable
	holds      map[string]*prefixTable
	markers    []string // distinct, in declaration order
	scanners   map[string]*scanner
	first      map[string]int
	duplicated map[string]bool
	sections   map[string]*section
	order      []string // section names in creation order (deterministic iteration)
	length     int
	window     string
	poisoned   bool
}

func newDerivedReducer(lens *DerivedLens, fields map[string]*streamField, names []string) *derivedReducer {
	wanted := map[string]bool{}
	for _, n := range names {
		wanted[n] = true
	}
	r := &derivedReducer{fields: fields, holds: map[string]*prefixTable{}, scanners: map[string]*scanner{},
		first: map[string]int{}, duplicated: map[string]bool{}, sections: map[string]*section{}}
	var markers []string
	for _, a := range lens.Anchors {
		if !wanted[a.Name] {
			continue
		}
		w := wantedAnchor{a.Name, RStrip(a.Prefix), Strip(a.Suffix)}
		r.wanted = append(r.wanted, w)
		markers = append(markers, w.marker)
	}
	r.tail = Strip(lens.Tail)
	if r.tail != "" {
		markers = append(markers, r.tail)
	}
	r.bounds = newPrefixTable(markers)
	for _, w := range r.wanted {
		if _, ok := r.holds[w.close]; !ok {
			all := append([]string{}, markers...)
			if w.close != "" {
				all = append(all, w.close)
			}
			r.holds[w.close] = newPrefixTable(all)
		}
	}
	for _, m := range markers {
		if _, ok := r.scanners[m]; !ok {
			r.scanners[m] = newScanner(m, 0)
			r.markers = append(r.markers, m)
		}
	}
	return r
}

func (r *derivedReducer) feed(delta string, final bool) {
	a := r.length
	b := a + len(delta)
	r.length = b
	if r.bounds.longest > 0 {
		w := r.window + delta
		if len(w) > r.bounds.longest {
			w = w[len(w)-r.bounds.longest:]
		}
		r.window = w
	}

	// 1. boundary occurrences (first position, duplicates) — global, like strings.Count
	for _, m := range r.markers {
		for _, q := range r.scanners[m].feed(delta) {
			if _, seen := r.first[m]; seen {
				r.duplicated[m] = true
			} else {
				r.first[m] = q
			}
		}
	}

	// 2. sections in batch order: sorted first occurrences, tail last on ties
	var bounds []boundary
	for _, w := range r.wanted {
		if p, ok := r.first[w.marker]; ok {
			bounds = append(bounds, boundary{p, p + len(w.marker), w.name, w.close})
		}
	}
	if p, ok := r.first[r.tail]; ok && r.tail != "" {
		bounds = append(bounds, boundary{p, p, "", ""})
	}
	sort.SliceStable(bounds, func(i, j int) bool {
		if bounds[i].start != bounds[j].start {
			return bounds[i].start < bounds[j].start
		}
		return bounds[i].after < bounds[j].after
	})
	for i, bd := range bounds {
		if bd.name == "" {
			continue
		}
		sec := r.sections[bd.name]
		if sec == nil {
			field := r.fields[bd.name]
			field.present = true
			sec = &section{field: field, start: bd.start, after: bd.after, close: bd.suffix,
				end: -1, received: bd.after, hold: r.holds[bd.suffix]}
			if bd.suffix != "" {
				sec.scanner = newScanner(bd.suffix, bd.after)
			}
			r.sections[bd.name] = sec
			r.order = append(r.order, bd.name)
		}
		end := -1
		if i+1 < len(bounds) {
			end = bounds[i+1].start
		}
		if sec.end >= 0 && end >= 0 && end < sec.end && sec.fixed != nil {
			panic("stream projection for " + bd.name + " revised emitted text")
		}
		sec.end = end
	}

	// 3. route the delta into sections; feed close scanners
	for _, name := range r.order {
		sec := r.sections[name]
		limit := b
		if sec.end >= 0 && sec.end < b {
			limit = sec.end
		}
		switch {
		case sec.fixed != nil:
			// raw is final; only its close scanner keeps counting
		case sec.received < limit:
			from := sec.received - a
			if from < 0 {
				from = 0
			}
			sec.held += delta[from : limit-a]
			sec.received = limit
		case sec.received > limit:
			sec.held = sec.cut(limit) // a boundary landed inside held text
			sec.received = limit
		}
		if sc := sec.scanner; sc != nil && sc.end < b && (sec.end < 0 || sc.end < sec.end) {
			from := sc.end - a
			if from < 0 {
				from = 0
			}
			sec.closeStarts = append(sec.closeStarts, sc.feed(delta[from:])...)
		}
	}

	// 4. the longest boundary prefix still growing at the end of the text
	growStart := b - r.bounds.hold(r.window)

	// 5. resolve: duplicates, fixes, and stable emission
	poisoned := len(r.duplicated) > 0
	for _, name := range r.order {
		sec := r.sections[name]
		end := sec.end
		var closes []int
		for _, q := range sec.closeStarts {
			if end < 0 || q+len(sec.close) <= end {
				closes = append(closes, q)
			}
		}
		if len(closes) >= 2 {
			poisoned = true
		}
		if sec.fixed != nil {
			continue
		}
		stop := b
		if end >= 0 {
			stop = end
		}
		firstClose := -1
		if len(closes) > 0 {
			firstClose = closes[0]
		}
		switch {
		case end >= 0 && end <= sec.after:
			sec.fix(sec.after)
		case final:
			if firstClose >= 0 {
				sec.fix(firstClose)
			} else {
				sec.fix(stop)
			}
		case end >= 0 && growStart >= end:
			if firstClose >= 0 {
				sec.fix(firstClose)
			} else {
				sec.fix(end)
			}
		case firstClose >= 0 && end < 0 && growStart >= firstClose+len(sec.close):
			sec.fix(firstClose)
		case !r.bounds.growsBetween(r.window, b, sec.start-1, sec.after):
			sec.advance(firstClose)
		}
	}
	r.poisoned = poisoned
}

func (r *derivedReducer) finalRaw() map[string]string {
	out := map[string]string{}
	for name, sec := range r.sections {
		if sec.fixed != nil {
			out[name] = *sec.fixed
		}
	}
	return out
}

// ----------------------------------------------------------------- stream

// Stream is a plan-bound streaming parse reducer. Create it with Plan.Stream.
type Stream struct {
	plan       *Plan
	pieces     strings.Builder
	parts      []*Object
	partTexts  []*strings.Builder // nil for parts without text
	partMode   bool
	finished   bool
	fields     map[string]*streamField
	stages     []streamStage
	byField    map[string][]streamStage
	counted    map[string]int
	derived    *derivedReducer
	lensStream LensStreamReducer
	lensPrefix map[string]string
	lensFinal  map[string]bool
}

type streamStage struct {
	field   string
	text    textStage     // nil for channel routings
	channel *channelStage // nil for text routings
}

func (st streamStage) captured() []string {
	if st.channel != nil {
		return st.channel.captured()
	}
	return st.text.captured()
}

// Stream creates a fresh pure reducer.
func (p *Plan) Stream() *Stream {
	s := &Stream{plan: p, fields: map[string]*streamField{}, byField: map[string][]streamStage{},
		counted: map[string]int{}, lensPrefix: map[string]string{}}
	for _, f := range p.Signature.Fields {
		s.fields[f.Name] = &streamField{name: f.Name}
	}
	names := make([]string, len(p.VisibleOutputs))
	for i, field := range p.VisibleOutputs {
		names[i] = field.Name
	}
	for _, route := range p.routings {
		from, _ := route.spec.Str("from")
		var st streamStage
		st.field = route.field
		switch {
		case strings.HasPrefix(from, "channel:"):
			st.channel = &channelStage{kind: from[len("channel:"):]}
		case route.spec.Has("between"):
			st.text = newBetweenStage(route.spec)
		case route.spec.Has("line_prefixed"):
			st.text = newLineStage(route.spec)
		default:
			st.text = newPatternStage(route.spec)
		}
		s.stages = append(s.stages, st)
		s.byField[route.field] = append(s.byField[route.field], st)
	}
	if lens, ok := p.Lens.(*DerivedLens); ok {
		s.derived = newDerivedReducer(lens, s.fields, names)
	} else if lens, ok := p.Lens.(StreamingLens); ok {
		s.lensStream = lens.NewStream(names)
	}
	return s
}

type partDelta struct {
	kind    string
	text    *string
	newPart bool
}

// Feed accepts one text string or lm15-shaped part delta.
func (s *Stream) Feed(delta any) (events []any, err error) {
	if s.finished {
		return nil, errors.New("stream is already finished")
	}
	defer catch(&err)
	text, part := s.append(delta)
	s.run(text, part, false)
	return s.events(false, nil, nil), nil
}

// Finish marks EOF, runs the authoritative batch parser, and returns EOF events and values.
func (s *Stream) Finish() (result *StreamResult, err error) {
	if s.finished {
		return nil, errors.New("stream is already finished")
	}
	s.finished = true
	defer catch(&err)
	var response any = s.pieces.String()
	if s.partMode {
		response = Obj("content", s.materializedParts())
	}
	values, spans := s.plan.parseWithSpans(response)
	s.run("", nil, true)
	return &StreamResult{Events: s.events(true, spans, values), Values: values}, nil
}

func (s *Stream) append(delta any) (string, *partDelta) {
	if text, ok := delta.(string); ok {
		s.pieces.WriteString(text)
		if s.partMode {
			return text, s.appendPart(TextPart(text))
		}
		return text, nil
	}
	part := validateResponsePart(delta)
	kind, _ := part.Str("kind")
	if !s.partMode {
		s.partMode = true
		if s.pieces.Len() > 0 {
			s.appendPart(TextPart(s.pieces.String()))
		}
	}
	pd := s.appendPart(part.Clone())
	text := ""
	if kind == "text" {
		text, _ = part.Str("text")
		s.pieces.WriteString(text)
	}
	return text, pd
}

func (s *Stream) appendPart(part *Object) *partDelta {
	kind, _ := part.Str("kind")
	text, hasText := part.Str("text")
	if hasText && len(s.parts) > 0 {
		previous := s.parts[len(s.parts)-1]
		pk, _ := previous.Str("kind")
		if pk == kind && s.partTexts[len(s.partTexts)-1] != nil {
			s.partTexts[len(s.partTexts)-1].WriteString(text)
			for _, key := range part.Keys {
				if key != "kind" && key != "text" {
					value, _ := part.Get(key)
					previous.Set(key, DeepClone(value))
				}
			}
			return &partDelta{kind: kind, text: &text, newPart: false}
		}
	}
	s.parts = append(s.parts, part)
	var b *strings.Builder
	var t *string
	if hasText {
		b = &strings.Builder{}
		b.WriteString(text)
		t = &text
	}
	s.partTexts = append(s.partTexts, b)
	return &partDelta{kind: kind, text: t, newPart: true}
}

func (s *Stream) materializedParts() []any {
	out := make([]any, 0, len(s.parts))
	for i, part := range s.parts {
		if b := s.partTexts[i]; b != nil {
			part = part.Clone()
			part.Set("text", b.String())
		}
		out = append(out, part)
	}
	return out
}

// ------------------------------------------------------------ projection

func (s *Stream) run(text string, part *partDelta, final bool) {
	stageText := text
	for _, st := range s.stages {
		f := s.fields[st.field]
		if st.channel != nil {
			if part != nil {
				delta := st.channel.part(part.kind, part.text, part.newPart)
				if st.channel.anyPart {
					f.present = true
				}
				if len(s.byField[st.field]) == 1 {
					f.emit(delta)
				}
			}
			continue
		}
		stageText = st.text.feed(stageText, final)
		captures := st.text.captured()
		if len(captures) > 0 {
			f.present = true
		}
		if len(s.byField[st.field]) == 1 {
			done := s.counted[st.field]
			for _, capture := range captures[done:] {
				if done > 0 {
					capture = "\n" + capture
				}
				f.emit(capture)
				done++
			}
			s.counted[st.field] = done
		}
	}
	if s.derived != nil {
		s.derived.feed(stageText, final)
	} else if s.lensStream != nil {
		var prefixes map[string]string
		if stageText != "" || !final {
			prefixes = s.lensStream.Feed(stageText)
		}
		if final {
			prefixes = s.lensStream.Finish()
			s.lensFinal = map[string]bool{}
			for name := range prefixes {
				s.lensFinal[name] = true
			}
		}
		names := make([]string, 0, len(prefixes))
		for name := range prefixes {
			names = append(names, name)
		}
		sort.Strings(names)
		for _, name := range names {
			raw := prefixes[name]
			f := s.fields[name]
			if f == nil {
				continue
			}
			f.present = true
			before := s.lensPrefix[name]
			if !strings.HasPrefix(raw, before) {
				panic("lens stream prefix for " + name + " revised emitted text")
			}
			s.lensPrefix[name] = raw
			f.emit(raw[len(before):])
		}
	}
}

// finalProjection: what the incremental projection says each present
// field's raw text is at EOF — checked against the batch spans.
func (s *Stream) finalProjection() map[string]string {
	out := map[string]string{}
	if s.derived != nil {
		for name, raw := range s.derived.finalRaw() {
			out[name] = raw
		}
	} else if s.lensStream != nil {
		for name, raw := range s.lensPrefix {
			out[name] = raw
		}
	}
	for field, stages := range s.byField {
		f := s.fields[field]
		if !f.present {
			continue
		}
		if len(stages) > 1 {
			var values []string
			for _, st := range stages {
				values = append(values, st.captured()...)
			}
			out[field] = strings.Join(values, "\n")
		} else {
			out[field] = f.emittedText()
		}
	}
	return out
}

// ----------------------------------------------------------------- events

func (s *Stream) events(final bool, finalSpans map[string]Span, values *Object) (events []any) {
	if s.derived != nil && s.derived.poisoned && !final {
		// A later delta can still supersede this provisional structural
		// reading; Finish invokes the batch parser and raises the
		// authoritative refusal. Pending text waits.
		return nil
	}
	if final {
		projected := s.finalProjection()
		if s.lensStream != nil {
			expected := map[string]bool{}
			for _, field := range s.plan.VisibleOutputs {
				expected[field.Name] = true
			}
			if len(s.lensFinal) != len(expected) {
				panic("lens stream fields disagree with batch fields")
			}
			for name := range s.lensFinal {
				if !expected[name] {
					panic("lens stream fields disagree with batch fields")
				}
			}
		}
		for name, raw := range projected {
			if span, ok := finalSpans[name]; ok && raw != span.Text() {
				panic("stream projection disagrees with batch parse for " + name)
			}
		}
		for _, field := range s.plan.Signature.Fields {
			span, ok := finalSpans[field.Name]
			if !ok {
				continue
			}
			f := s.fields[field.Name]
			if !f.started {
				f.started = true
				events = append(events, Obj("kind", "field_started", "field", field.Name))
			}
			raw := span.Text()
			before := f.emittedText()
			heldBack := strings.Join(f.pending, "")
			already := before[:len(before)-len(heldBack)]
			if !strings.HasPrefix(raw, already) {
				panic("stream projection revised emitted text for " + field.Name)
			}
			if delta := raw[len(already):]; delta != "" {
				events = append(events, Obj("kind", "field_delta", "field", field.Name, "text", delta))
			}
			value, _ := values.Get(field.Name)
			events = append(events, Obj("kind", "field_done", "field", field.Name, "value", value))
		}
		return events
	}
	for _, field := range s.plan.Signature.Fields {
		f := s.fields[field.Name]
		if !f.present {
			continue
		}
		if !f.started {
			f.started = true
			events = append(events, Obj("kind", "field_started", "field", field.Name))
		}
		if len(f.pending) > 0 {
			text := strings.Join(f.pending, "")
			f.pending = f.pending[:0]
			events = append(events, Obj("kind", "field_delta", "field", field.Name, "text", text))
		}
	}
	return events
}

// DescribeStreaming makes every buffering choice inspectable.
func (p *Plan) DescribeStreaming() *Object {
	counts := map[string]int{}
	for _, route := range p.routings {
		counts[route.field]++
	}
	routes := []any{}
	modes := []string{}
	consumingPattern := false
	for _, route := range p.routings {
		from, _ := route.spec.Str("from")
		mode, reason := "incremental", ""
		if route.spec.Has("pattern") {
			mode, reason = "buffered", "pattern routing waits for EOF"
			consumingPattern = consumingPattern || route.spec.Bool("consume", false)
		} else if counts[route.field] > 1 {
			mode, reason = "buffered", "multiple routings concatenate by declaration order"
		}
		item := Obj("field", route.field, "from", from, "mode", mode)
		if reason != "" {
			item.Set("reason", reason)
		}
		routes = append(routes, item)
		modes = append(modes, mode)
	}
	lensMode, lensReason := "buffered", "lens provides no streaming face"
	_, derived := p.Lens.(*DerivedLens)
	_, custom := p.Lens.(StreamingLens)
	if (derived || custom) && !consumingPattern {
		lensMode, lensReason = "incremental", ""
	} else if derived || custom {
		lensReason = "a consuming pattern routing can revise lens text"
	}
	lens := Obj("mode", lensMode)
	if lensReason != "" {
		lens.Set("reason", lensReason)
	}
	modes = append(modes, lensMode)
	allIncremental, allBuffered := true, true
	for _, mode := range modes {
		allIncremental = allIncremental && mode == "incremental"
		allBuffered = allBuffered && mode == "buffered"
	}
	mode := "hybrid"
	if allIncremental {
		mode = "incremental"
	} else if allBuffered {
		mode = "buffered"
	}
	return Obj("mode", mode, "lens", lens, "routings", routes, "field_done", "finish")
}
