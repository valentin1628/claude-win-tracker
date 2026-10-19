#!/usr/bin/env bash
# CI macOS : lance l'appli construite 45 s (au-delà des minuteries de 30 s) sous fs_usage,
# puis échoue si elle a touché un dossier protégé (Bureau, Documents, Photos, iCloud…).
# Ce sont ces accès qui déclenchent les demandes d'autorisation de macOS.
set -uo pipefail
cd "$(dirname "$0")/.."

# De faux journaux Claude Code, pour que l'analyse des coûts tourne aussi.
mkdir -p ~/.claude/projects/demo
echo '{"type":"assistant","timestamp":"2026-01-01T00:00:00Z","requestId":"r","message":{"id":"m","model":"claude-sonnet-4-5","usage":{"input_tokens":10,"output_tokens":5}}}' \
    > ~/.claude/projects/demo/a.jsonl

# Lancée avec open, comme depuis le Finder (dossier courant /, LaunchServices).
sudo fs_usage -w -f filesys "Claude Usage Tra" > fs.log 2>&1 &
tracer=$!
sleep 2
open -W -n "dist/Claude Usage Tray.app" --args --exit-after 45
status=$?
sudo kill -INT "$tracer" 2>/dev/null
sleep 1

echo "--- fin de l'appli (code $status) ---"
echo "--- journal ---"
cat ~/Library/Logs/ClaudeTracker/*.log 2>/dev/null || true
echo "--- dossiers ouverts sous \$HOME (aperçu) ---"
grep -oE "$HOME/[^ ]+" fs.log | awk -F/ '{print "/"$2"/"$3"/"$4"/"$5}' | sort | uniq -c | sort -rn | head -40

# Chemins en début de colonne : /System/Volumes/Preboot (frameworks système) n'est pas un disque externe.
protected="[[:space:]]($HOME/(Desktop|Documents|Downloads|Pictures|Movies|Music|Library/Mobile Documents)|/Volumes/)"
if grep -qE "$protected" fs.log; then
    echo "::error::L'appli accède à des dossiers protégés (demandes d'autorisation macOS) :"
    grep -E "$protected" fs.log | head -40
    exit 1
fi
if [ "$status" -ne 0 ] || grep -q "Exception\|Erreur\|Fatal" ~/Library/Logs/ClaudeTracker/*.log 2>/dev/null; then
    echo "::error::L'appli a planté ou journalisé une erreur (code $status)"
    exit 1
fi
echo "OK : aucun accès à un dossier protégé, arrêt propre."
