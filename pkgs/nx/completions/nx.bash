_nx() {
  local cur="${COMP_WORDS[COMP_CWORD]}" cmd="${COMP_WORDS[1]}"
  if [[ $COMP_CWORD -eq 1 ]]; then
    COMPREPLY=($(compgen -W "status check pull switch update gen rollback clean optimise" -- "$cur"))
  elif [[ $cmd == update ]]; then
    COMPREPLY=($(compgen -W "base desktop apps all --profiles --build --boot --commit --push --no-commit --yes" -- "$cur"))
  elif [[ $cmd == switch ]]; then
    COMPREPLY=($(compgen -W "--build --boot --test --yes" -- "$cur"))
  elif [[ $cmd == gen ]]; then
    COMPREPLY=($(compgen -W "list diff --last --json" -- "$cur"))
  fi
}
complete -F _nx nx
