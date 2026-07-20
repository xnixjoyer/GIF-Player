function gif --description "GIF-Overlay: Picker, Widgets & Steuerung"
    # Referenz-Implementierung - nutzt AUSSCHLIESSLICH das gif-script.py-CLI
    # (Widget-Erkennung ueber dessen PID-Dateien, robust unabhaengig davon,
    # ob ein GIF per fish, Picker oder Control-Panel gestartet wurde).
    set -l app_dir ~/Scripts/Gif-Overlay
    set -l script $app_dir/gif-script.py
    set -l gif_dir $app_dir/Gifs

    # gif  ->  Picker oeffnen
    if test (count $argv) -eq 0
        python3 $app_dir/gif-picker.py >/dev/null 2>&1 &
        disown
        return 0
    end

    switch $argv[1]
        case control panel
            python3 $app_dir/gif-control.py >/dev/null 2>&1 &
            disown
        case edit unlock
            python3 $script edit
        case lock
            python3 $script lock
        case list ls
            python3 $script list
        case kill-all stop-all killall
            python3 $script stop-all
        case help -h --help
            echo "gif                     Picker oeffnen"
            echo "gif <name>              GIF starten (mehrfach moeglich: name, name-2, ...)"
            echo "gif <name> stop         GIF beenden"
            echo "gif <name> <befehl>     IPC: move x y | move-by dx dy | scale s |"
            echo "                             opacity o | speed s | flip h/v/none |"
            echo "                             corner tl/tr/bl/br/center | bounce |"
            echo "                             hop | jump | jump-rate s | pause |"
            echo "                             play | reset | status | lock | unlock"
            echo "gif edit / gif lock     Edit-Modus fuer ALLE an/aus"
            echo "gif control             Control-Panel oeffnen"
            echo "gif list                Laufende Widgets anzeigen"
            echo "gif kill-all            Alle Widgets beenden"
        case '*'
            set -l name $argv[1]
            if test (count $argv) -eq 1
                # GIF-Datei suchen (auch in Kategorie-Unterordnern)
                set -l file (command find $gif_dir -name "$name.gif" -print -quit 2>/dev/null)
                if test -z "$file"
                    echo "gif: '$name.gif' nicht gefunden in $gif_dir" >&2
                    return 1
                end
                # Mehrfachstart erlaubt: das Script vergibt automatisch
                # Instanz-IDs (name, name-2, ...)
                python3 $script run $file >/dev/null 2>&1 &
                disown
            else if contains -- $argv[2] stop quit
                python3 $script ipc $name quit
            else
                python3 $script ipc $name $argv[2..-1]
            end
    end
end
