_nx() {
  local cur="${COMP_WORDS[COMP_CWORD]}" cmd="${COMP_WORDS[1]}"
  local prev="${COMP_WORDS[COMP_CWORD-1]}" action="" i
  if [[ $prev == --profile ]]; then
    mapfile -t COMPREPLY < <(compgen -f -- "$cur")
    return
  fi
  if [[ $COMP_CWORD -eq 1 ]]; then
    COMPREPLY=($(compgen -W "status check pull switch update profiles gen rollback clean optimise" -- "$cur"))
  elif [[ $cmd == update ]]; then
    if [[ ${COMP_WORDS[2]} == profiles ]]; then
      COMPREPLY=($(compgen -W "--profile --yes" -- "$cur"))
    else
      COMPREPLY=($(compgen -W "base desktop apps all profiles --profile --profiles --build --boot --commit --push --no-commit --yes" -- "$cur"))
    fi
  elif [[ $cmd == profiles ]]; then
    for ((i=2; i<COMP_CWORD; i++)); do
      if [[ ${COMP_WORDS[i]} == --profile ]]; then
        ((i++))
        continue
      fi
      case "${COMP_WORDS[i]}" in
        list|ls|install|add|remove|rm|update|upgrade|history|rollback)
          action="${COMP_WORDS[i]}"; break ;;
      esac
    done
    case "$action" in
      "") COMPREPLY=($(compgen -W "list install remove update history rollback --profile --json --yes" -- "$cur")) ;;
      list|ls|history) COMPREPLY=($(compgen -W "--profile --json" -- "$cur")) ;;
      *) COMPREPLY=($(compgen -W "--profile --yes" -- "$cur")) ;;
    esac
  elif [[ $cmd == switch ]]; then
    COMPREPLY=($(compgen -W "--build --boot --test --yes" -- "$cur"))
  elif [[ $cmd == gen ]]; then
    COMPREPLY=($(compgen -W "list diff --last --json" -- "$cur"))
  fi
}
complete -F _nx nx
