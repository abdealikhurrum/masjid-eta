-- Drive the WhatsApp Desktop (macOS) app to deliver a message to a group.
-- The message must already be on the clipboard (the CLI puts it there).
--
-- Usage:  osascript send_whatsapp.applescript "Group Name" send
--         osascript send_whatsapp.applescript "Group Name" stage   (everything but the final send)
--
-- Requires Accessibility permission for whatever runs it (Terminal / iTerm / the
-- Python process): System Settings > Privacy & Security > Accessibility.

on run argv
    if (count of argv) < 1 then error "group name required"
    set theGroup to item 1 of argv
    set doSend to ((count of argv) > 1 and item 2 of argv is "send")

    tell application "WhatsApp" to activate
    delay 1.2

    tell application "System Events"
        if not (exists process "WhatsApp") then error "WhatsApp is not running"
        tell process "WhatsApp"
            set frontmost to true
            delay 0.3
            keystroke "n" using {command down}      -- open New chat / search
            delay 0.9
            keystroke theGroup                       -- type the group name
            delay 1.3
            key code 36                              -- Return: open the top match
            delay 1.1
            keystroke "v" using {command down}       -- paste message from clipboard
            delay 0.7
            if doSend then
                key code 36                          -- Return: send
                delay 0.4
            end if
        end tell
    end tell
end run
