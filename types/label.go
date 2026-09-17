package types

import "fmt"

// LabelMap maps ROM addresses to human-readable label names.
// It is a type alias for map[uint32]string so it is fully interchangeable
// with the underlying map type across all packages.
type LabelMap = map[Addr]string

// LookupOrHex returns the label name for addr from labels, or the raw address
// when addr has no symbol.
//
// The fallback must be an address literal, not a generated "loc_XXXXXX": such a
// name is only defined where the segment writer actually emits it, i.e. for
// branch targets inside the same segment. Targets in another segment or inside
// a `bin` data block got a name nothing defined, and the output stopped
// assembling with "Symbol 'loc_XXXXXX' does not exist". Callers that want the
// pretty name for an intra-segment target pre-seed it into labels.
func LookupOrHex(labels LabelMap, addr Addr) string {
	if name, ok := labels[addr]; ok {
		return name
	}
	return fmt.Sprintf("$%06X", addr)
}
