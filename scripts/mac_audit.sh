#!/usr/bin/env bash
# CI macOS : lance l'appli construite 45 s (au-delà des minuteries de 30 s) sous fs_usage,
# puis échoue si elle a touché un dossier protégé (Bureau, Documents, Photos, iCloud…).
# Ce sont ces accès qui déclenchent les demandes d'autorisation de macOS.
set -uo pipefail
cd "$(dirname "$0")/.."
bin="dist/Claude Usage Tray.app/Contents/MacOS/Claude Usage Tray"

# De faux journaux Claude Code, pour que l'analyse des coûts tourne aussi.
mkdir -p ~/.claude/projects/demo
echo '{"type":"assistant","timestamp":"2026-01-01T00:00:00Z","requestId":"r","message":{"id":"m","model":"claude-sonnet-4-5","usage":{"input_tokens":10,"output_tokens":5}}}' \
    > ~/.claude/projects/demo/a.jsonl

"$bin" --exit-after 45 > app.out 2>&1 &
pid=$!
sudo fs_usage -w -f filesys "$pid" > fs.log 2>&1 &
tracer=$!
wait "$pid"
status=$?
sudo kill -INT "$tracer" 2>/dev/null
sleep 1

echo "--- sortie de l'appli (code $status) ---"
cat app.out
echo "--- journal ---"
cat ~/Library/Logs/ClaudeTracker/*.log 2>/dev/null || true
echo "--- dossiers ouverts sous \$HOME (aperçu) ---"
grep -oE "$HOME/[^ ]+" fs.log | awk -F/ '{print "/"$2"/"$3"/"$4"/"$5}' | sort | uniq -c | sort -rn | head -40

protected="$HOME/(Desktop|Documents|Downloads|Pictures|Movies|Music|Library/Mobile Documents)|/Volumes/"
if grep -qE "$protected" fs.log; then
    echo "::error::L'appli accède à des dossiers protégés (demandes d'autorisation macOS) :"
    grep -E "$protected" fs.log | head -40
    exit 1
fi
if [ "$status" -ne 0 ]; then
    echo "::error::L'appli s'est arrêtée avec le code $status"
    exit 1
fi
echo "OK : aucun accès à un dossier protégé, arrêt propre."
