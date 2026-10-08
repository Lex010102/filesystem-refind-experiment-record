cd '/Users/wangwenqi/Desktop/memory bench' || return 1

if [[ -z ${FSMEM_API_KEY-} ]]; then
  printf 'FSMEM_API_KEY is not present in this terminal. Background run was not started.\n' >&2
  return 1
fi

export FSMEM_API_KEY
export FSMEM_API_BASE_URL='https://soclaas-api.comp.nus.edu.sg/v1'
export FSMEM_MODEL='coding'
export FSMEM_API_STYLE='portable'

umask 077
background_dir='local-runs/s3-background'
pid_file="$background_dir/resume-s3.pid"
mkdir -p "$background_dir"

if [[ -f $pid_file ]]; then
  existing_pid=$(<"$pid_file")
  if [[ $existing_pid == <-> ]] && kill -0 "$existing_pid" 2>/dev/null; then
    printf 'S3 is already running in background (PID %s).\n' "$existing_pid"
    return 0
  fi
fi

timestamp=$(date -u '+%Y%m%dT%H%M%SZ')
log_file="$background_dir/resume-s3-$timestamp.log"

background_nice_option=${options[BG_NICE]-off}
unsetopt BG_NICE
nohup python3 -m fs_memory_lab.cli resume-s3 \
  --run-id '20261006T022525914538Z-a1352213' \
  --source-code-revision 'b41971f049501c286ad55017bdc1157e1bbdbc59' \
  >"$log_file" 2>&1 </dev/null &
background_pid=$!
if [[ $background_nice_option == on ]]; then
  setopt BG_NICE
fi

printf '%s\n' "$background_pid" >"$pid_file"
printf '%s\n' "$log_file" >"$background_dir/latest-log.path"
disown "$background_pid" 2>/dev/null || true

printf 'S3 background run started. PID: %s\n' "$background_pid"
printf 'Log: %s/%s\n' "$PWD" "$log_file"
printf 'This terminal is free; closing it will not stop the run.\n'
