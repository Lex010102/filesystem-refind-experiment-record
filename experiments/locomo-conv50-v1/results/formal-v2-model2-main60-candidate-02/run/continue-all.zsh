#!/bin/zsh
set -euo pipefail
umask 077

repo_root='/Users/wangwenqi/Desktop/memory bench'
output_root="$repo_root/local-runs/formal-v2-model2"
suite_id='formal-v2-model2-main60-candidate-02'
suite_root="$output_root/$suite_id"
launcher_lock="$suite_root/formal-launcher.lock"
pid_file="$suite_root/formal-launcher.pid"
keychain_service='filesystem-refind-experiment-record.soclaas-api-key'
keychain_account="${USER:-wangwenqi}"

touch "$launcher_lock"
zmodload zsh/system
if ! zsystem flock -t 0 -f continuation_launcher_fd "$launcher_lock"; then
  print -u2 'Another Model 2 launcher holds formal-launcher.lock.'
  exit 44
fi

unset FSMEM_API_KEY
if ! continuation_model2_key="$(
  /usr/bin/security find-generic-password \
    -a "$keychain_account" \
    -s "$keychain_service" \
    -w 2>/dev/null
)"; then
  print -u2 'No non-interactive SoCLaaS credential is available in Keychain.'
  exit 43
fi
export FSMEM_API_KEY="$continuation_model2_key"
export FSMEM_API_BASE_URL='https://soclaas-api.comp.nus.edu.sg/v1'
export FSMEM_MODEL='x-test-2'
export FSMEM_API_STYLE='portable'

cleanup() {
  unset FSMEM_API_KEY continuation_model2_key
  zsystem flock -u "$continuation_launcher_fd" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

print -r -- "$$" >| "$pid_file"
cd "$repo_root"

continuation=(python3 "$suite_root/continuation_runner.py")
formal_cli=(
  python3 -m fs_memory_lab.formal_v2_model2_cli
  --repo-root "$repo_root"
  --output-root "$output_root"
  --suite-id "$suite_id"
)

main_completed=$(jq -r '.children.main40.completed // 0' "$suite_root/status.json")
main_start=$((main_completed / 35 + 1))
if (( main_start <= 8 )); then
  for (( local_block = main_start; local_block <= 8; local_block++ )); do
    "${continuation[@]}" run-child --child main40 --through-block "$local_block"
    "${formal_cli[@]}" audit-batch --global-batch "$local_block"
  done
fi

extension_completed=$(jq -r '.children.extension20.completed // 0' "$suite_root/status.json")
extension_start=$((extension_completed / 35 + 1))
if (( extension_start <= 4 )); then
  for (( local_block = extension_start; local_block <= 4; local_block++ )); do
    global_batch=$((local_block + 8))
    "${continuation[@]}" run-child --child extension20 --through-block "$local_block"
    "${formal_cli[@]}" audit-batch --global-batch "$global_batch"
  done
fi

"${continuation[@]}" verify
