#!/bin/zsh
set -euo pipefail
umask 077

repo_root='/Users/wangwenqi/Desktop/memory bench'
output_root='local-runs/llm-judge-x-test1-main120'
keychain_service='filesystem-refind-experiment-record.soclaas-api-key'
keychain_account="${USER:-wangwenqi}"

unset FSMEM_API_KEY
if ! fsmem_judge_key="$(
  /usr/bin/security find-generic-password \
    -a "$keychain_account" \
    -s "$keychain_service" \
    -w 2>/dev/null
)"; then
  printf '%s\n' 'No non-interactive SoCLaaS credential is available in Keychain.' >&2
  exit 43
fi
export FSMEM_API_KEY="$fsmem_judge_key"
export FSMEM_API_BASE_URL='https://soclaas-api.comp.nus.edu.sg/v1'
export FSMEM_MODEL='x-test-1'
export FSMEM_API_STYLE='portable'
trap 'unset FSMEM_API_KEY fsmem_judge_key' EXIT HUP INT TERM

cd "$repo_root"

python3 -m fs_memory_lab.judge_main60 \
  --repo-root "$repo_root" \
  --output-root "$output_root" \
  --judge-run-id 'llm-judge-x-test1-model1-main60-run-01' \
  --source-system-id 'model1' \
  --partition main40 \
    'local-runs/formal-v1-main40' \
    'formal-v1-main40-run-02' \
    'experiments/locomo-conv50-v1/question-sets/main-40-gold.jsonl' \
    'a6833ca585ca26efcdd038a5cf202fd46657999053ebd7b8cc73793f7544718b' \
  --partition extension20 \
    'local-runs/formal-v2-qwen-extension20' \
    'formal-v2-qwen-extension20-run-01' \
    'experiments/locomo-conv50-v1/question-sets-main60-v2/extension-20-gold.jsonl' \
    'c8b08771af27537579e418db0ace600076cd09108019fc86cd584740bb035ec8' \
  preflight

python3 -m fs_memory_lab.judge_main60 \
  --repo-root "$repo_root" \
  --output-root "$output_root" \
  --judge-run-id 'llm-judge-x-test1-model1-main60-run-01' \
  --source-system-id 'model1' \
  --partition main40 \
    'local-runs/formal-v1-main40' \
    'formal-v1-main40-run-02' \
    'experiments/locomo-conv50-v1/question-sets/main-40-gold.jsonl' \
    'a6833ca585ca26efcdd038a5cf202fd46657999053ebd7b8cc73793f7544718b' \
  --partition extension20 \
    'local-runs/formal-v2-qwen-extension20' \
    'formal-v2-qwen-extension20-run-01' \
    'experiments/locomo-conv50-v1/question-sets-main60-v2/extension-20-gold.jsonl' \
    'c8b08771af27537579e418db0ace600076cd09108019fc86cd584740bb035ec8' \
  run-all

python3 -m fs_memory_lab.judge_main60 \
  --repo-root "$repo_root" \
  --output-root "$output_root" \
  --judge-run-id 'llm-judge-x-test1-model2-main60-run-01' \
  --source-system-id 'model2' \
  --partition main40 \
    'local-runs/formal-v2-model2/formal-v2-model2-main60-candidate-02/children/main40' \
    'formal-v2-model2-main60-candidate-02-main40' \
    'experiments/locomo-conv50-v1/question-sets/main-40-gold.jsonl' \
    'a6833ca585ca26efcdd038a5cf202fd46657999053ebd7b8cc73793f7544718b' \
  --partition extension20 \
    'local-runs/formal-v2-model2/formal-v2-model2-main60-candidate-02/children/extension20' \
    'formal-v2-model2-main60-candidate-02-extension20' \
    'experiments/locomo-conv50-v1/question-sets-main60-v2/extension-20-gold.jsonl' \
    'c8b08771af27537579e418db0ace600076cd09108019fc86cd584740bb035ec8' \
  preflight

python3 -m fs_memory_lab.judge_main60 \
  --repo-root "$repo_root" \
  --output-root "$output_root" \
  --judge-run-id 'llm-judge-x-test1-model2-main60-run-01' \
  --source-system-id 'model2' \
  --partition main40 \
    'local-runs/formal-v2-model2/formal-v2-model2-main60-candidate-02/children/main40' \
    'formal-v2-model2-main60-candidate-02-main40' \
    'experiments/locomo-conv50-v1/question-sets/main-40-gold.jsonl' \
    'a6833ca585ca26efcdd038a5cf202fd46657999053ebd7b8cc73793f7544718b' \
  --partition extension20 \
    'local-runs/formal-v2-model2/formal-v2-model2-main60-candidate-02/children/extension20' \
    'formal-v2-model2-main60-candidate-02-extension20' \
    'experiments/locomo-conv50-v1/question-sets-main60-v2/extension-20-gold.jsonl' \
    'c8b08771af27537579e418db0ace600076cd09108019fc86cd584740bb035ec8' \
  run-all
