cd '/Users/wangwenqi/Desktop/memory bench' || return 1

if [[ -z ${FSMEM_API_KEY-} ]]; then
  read -r -s "FSMEM_API_KEY?Paste NEW school API key (hidden), then press Enter: "
  printf '\n'
  export FSMEM_API_KEY
fi

export FSMEM_API_BASE_URL='https://soclaas-api.comp.nus.edu.sg/v1'
export FSMEM_MODEL='coding'
export FSMEM_API_STYLE='portable'

python3 -m fs_memory_lab.cli resume-s3 \
  --run-id '20261006T022525914538Z-a1352213' \
  --source-code-revision '159ef8eb3e2815117b335a939b0f0dfc2dcbd5da'
