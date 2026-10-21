complete -c nx -f
complete -c nx -n __fish_use_subcommand -a status -d "host, generation, repository, cached updates"
complete -c nx -n __fish_use_subcommand -a check -d "which inputs have updates (fast)"
complete -c nx -n __fish_use_subcommand -a pull -d "fetch repository, fast-forward only"
complete -c nx -n __fish_use_subcommand -a switch -d "build, diff, activate"
complete -c nx -n __fish_use_subcommand -a update -d "update inputs, build, confirm, switch"
complete -c nx -n __fish_use_subcommand -a profiles -d "list and manage user-profile packages"
complete -c nx -n __fish_use_subcommand -a debug -d "detailed read-only diagnostics and logs"
complete -c nx -n __fish_use_subcommand -a gen -d "list or compare generations"
complete -c nx -n __fish_use_subcommand -a rollback -d "previous generation"
complete -c nx -n __fish_use_subcommand -a clean -d "delete old generations, free store"
complete -c nx -n __fish_use_subcommand -a optimise -d "deduplicate the store"
complete -c nx -n "__fish_seen_subcommand_from update; and not __fish_seen_subcommand_from profiles" -a "base desktop apps all profiles"
complete -c nx -n "__fish_seen_subcommand_from update; and not __fish_seen_subcommand_from profiles" -l build -l boot -l profiles -l commit -l push -l no-commit -s y -l yes
complete -c nx -n "__fish_seen_subcommand_from profiles update; and not __fish_seen_subcommand_from debug" -l profile -r -F -d "Nix user-profile path"
complete -c nx -n "__fish_seen_subcommand_from profiles; and not __fish_seen_subcommand_from debug list ls install add remove rm update upgrade history rollback" -a "list install remove update history rollback"
complete -c nx -n "__fish_seen_subcommand_from profiles; and not __fish_seen_subcommand_from debug install add remove rm update upgrade rollback" -l json
complete -c nx -n "__fish_seen_subcommand_from profiles; and not __fish_seen_subcommand_from debug list ls history" -s y -l yes
complete -c nx -n "__fish_seen_subcommand_from gen" -a "list diff"
complete -c nx -n "__fish_seen_subcommand_from switch" -l build -l boot -l test -s y -l yes
complete -c nx -n "__fish_seen_subcommand_from check status gen" -l json
complete -c nx -n "__fish_seen_subcommand_from debug" -a "system nix cache repo profiles boot services hardware network desktop logs build"
complete -c nx -n "__fish_seen_subcommand_from debug" -l list -l full -l json -l probe-cache -l strict
complete -c nx -n "__fish_seen_subcommand_from debug" -l output -l repo -l profile -l store-path -r -F
complete -c nx -n "__fish_seen_subcommand_from debug" -l host -l unit -l user-unit -l boot -l lines -l timeout -l budget -l max-bytes -r
