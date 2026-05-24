on run
  tell application "Microsoft Outlook"
    set acc to default account
    set foldersList to folders of acc
    set jsonRows to "["
    set idx to 0
    repeat with f in foldersList
      set idx to idx + 1
      set nm to name of f as text
      if idx > 1 then
        set jsonRows to jsonRows & ","
      end if
      set jsonRows to jsonRows & "\"" & my escape_json(nm) & "\""
    end repeat
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
