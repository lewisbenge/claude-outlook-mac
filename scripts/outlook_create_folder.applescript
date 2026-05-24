on run argv
  set pathText to item 1 of argv
  set parts to my split(pathText, "/")
  tell application "Microsoft Outlook"
    set parentRef to default account
    repeat with p in parts
      set partName to contents of p
      set found to missing value
      repeat with f in folders of parentRef
        if (name of f as text) is partName then
          set found to f
          exit repeat
        end if
      end repeat
      if found is missing value then
        set found to make new folder at parentRef with properties {name:partName}
      end if
      set parentRef to found
    end repeat
  end tell
  return "OK"
end run

on split(s, delim)
  set AppleScript's text item delimiters to delim
  set outList to text items of s
  set AppleScript's text item delimiters to ""
  return outList
end split
