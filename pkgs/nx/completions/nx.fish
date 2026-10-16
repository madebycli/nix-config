complete -c nx -f
complete -c nx -n __fish_use_subcommand -a status -d "host, generation, repository, cached updates"
complete -c nx -n __fish_use_subcommand -a check -d "which inputs have updates (fast)"
complete -c nx -n __fish_use_subcommand -a pull -d "fetch repository, fast-forward only"
complete -c nx -n __fish_use_subcommand -a switch -d "build, diff, activate"
complete -c nx -n __fish_use_subcommand -a update -d "update inputs, build, confirm, switch"
complete -c nx -n __fish_use_subcommand -a gen -d "list or compare generations"
complete -c nx -n __fish_use_subcommand -a rollback -d "previous generation"
complete -c nx -n __fish_use_subcommand -a clean -d "delete old generations, free store"
complete -c nx -n __fish_use_subcommand -a optimise -d "deduplicate the store"
complete -c nx -n "__fish_seen_subcommand_from update" -a "base desktop apps all"
complete -c nx -n "__fish_seen_subcommand_from gen" -a "list diff"
complete -c nx -n "__fish_seen_subcommand_from switch" -l build -l boot -l test -s y -l yes
complete -c nx -n "__fish_seen_subcommand_from check status gen" -l json
