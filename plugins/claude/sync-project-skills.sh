#!/usr/bin/env bash
# Mirror the Claude Code edition of the AO research/validation plugin into the
# repository's project-level skills, or check that the mirror is current.
#
#   plugins/claude/sync-project-skills.sh                     copy plugin -> .claude/
#   plugins/claude/sync-project-skills.sh --check             verify mirror, names, links
#   plugins/claude/sync-project-skills.sh --compare-original  diff against the Codex source
#
# The plugin directory is the editable source. Only these project paths are
# written: .claude/skills/ao-*/, .claude/references/, .claude/assets/.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PLUGIN="$HERE/ao-simulation-research-validation"
ORIGINAL="$ROOT/plugins/ao-simulation-research-validation"
PROJECT="$ROOT/.claude"

# Files under a tree root that belong to this plugin, relative to that root.
tree_files() {
  (cd "$1" 2>/dev/null && find skills/ao-* references assets -type f ! -name .DS_Store 2>/dev/null | LC_ALL=C sort) || true
}

# Report relative Markdown links that do not resolve inside a tree.
check_links() {
  local base="$1" bad=0 rel target
  while IFS= read -r rel; do
    case "$rel" in *.md) ;; *) continue ;; esac
    while IFS= read -r target; do
      case "$target" in http://*|https://*|mailto:*|\#*) continue ;; esac
      if [ ! -e "$(dirname "$base/$rel")/${target%%#*}" ]; then
        echo "BROKEN LINK  $base/$rel -> $target"
        bad=1
      fi
    done < <(grep -oE '\]\([^)[:space:]]+\)' "$base/$rel" | sed -E 's/^\]\((.*)\)$/\1/')
  done < <(tree_files "$base")
  return $bad
}

do_check() {
  local fail=0 rel differs skill
  if ! diff <(tree_files "$PLUGIN") <(tree_files "$PROJECT") >/dev/null; then
    echo "File sets differ (< plugin only, > .claude only):"
    diff <(tree_files "$PLUGIN") <(tree_files "$PROJECT") | grep '^[<>]' || true
    fail=1
  fi
  differs="$(tree_files "$PLUGIN" | while IFS= read -r rel; do
    if [ -f "$PROJECT/$rel" ] && ! cmp -s "$PLUGIN/$rel" "$PROJECT/$rel"; then
      echo "DIFFERS  .claude/$rel"
    fi
  done)"
  if [ -n "$differs" ]; then echo "$differs"; fail=1; fi
  for skill in "$PLUGIN"/skills/ao-*/; do
    skill="$(basename "$skill")"
    if ! grep -qx "name: $skill" "$PLUGIN/skills/$skill/SKILL.md"; then
      echo "NAME MISMATCH  skills/$skill/SKILL.md"
      fail=1
    fi
  done
  check_links "$PLUGIN" || fail=1
  check_links "$PROJECT" || fail=1
  if [ "$fail" -eq 0 ]; then
    echo "OK: $(tree_files "$PLUGIN" | wc -l | tr -d ' ') files mirrored identically; skill names and relative links resolve."
  fi
  return "$fail"
}

do_sync() {
  local rel changed=0
  while IFS= read -r rel; do
    if ! cmp -s "$PLUGIN/$rel" "$PROJECT/$rel" 2>/dev/null; then
      mkdir -p "$PROJECT/$(dirname "$rel")"
      cp -p "$PLUGIN/$rel" "$PROJECT/$rel"
      echo "updated  .claude/$rel"
      changed=$((changed + 1))
    fi
  done < <(tree_files "$PLUGIN")
  echo "$changed file(s) updated."
  do_check
}

case "${1:-}" in
  "") do_sync ;;
  --check) do_check ;;
  --compare-original)
    for tree in skills references assets; do
      diff -ru -x .DS_Store -x agents "$ORIGINAL/$tree" "$PLUGIN/$tree" || true
    done
    ;;
  *) echo "usage: $0 [--check | --compare-original]" >&2; exit 2 ;;
esac
