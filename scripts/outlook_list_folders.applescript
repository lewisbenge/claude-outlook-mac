on run
  tell application "Microsoft Outlook"
    set allAccounts to every exchange account
    if (count of allAccounts) is 0 then
      set allAccounts to every imap account
    end if
    if (count of allAccounts) is 0 then
      set allAccounts to every pop account
    end if
    if (count of allAccounts) is 0 then
      error "Outlook did not expose folder roots through AppleScript (no accounts available)." number 10001
    end if

    set jsonRows to "["
    set idx to 0

    repeat with acc in allAccounts
      set folderRoots to folders of acc
      if folderRoots is missing value then
        set folderRoots to {}
      end if

      repeat with f in folderRoots
        set idx to idx + 1
        set nm to name of f as text
        if idx > 1 then
          set jsonRows to jsonRows & ","
        end if
        set jsonRows to jsonRows & "\"" & my escape_json(nm) & "\""
      end repeat
    end repeat

    if idx is 0 then
      error "Outlook did not expose folder roots through AppleScript (accounts found, but no root folders were returned)." number 10002
    end if

    set jsonRows to jsonRows & "]"
    return jsonRows
  end tell
end run

on escape_json(s)
  set AppleScript's text item delimiters to "\""
  set parts to text items of s
  set AppleScript's text item delimiters to "\\\""
  set outText to parts as text
  set AppleScript's text item delimiters to ""
  return outText
end escape_json
