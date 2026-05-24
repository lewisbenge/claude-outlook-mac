on run argv
  set messageId to item 1 of argv
  set targetPath to item 2 of argv
  set parts to my split(targetPath, "/")
  tell application "Microsoft Outlook"
    set parentRef to default account
    repeat with p in parts
      set parentRef to folder (contents of p) of parentRef
    end repeat
    set inboxFolder to inbox of default account
    set targetMessage to first message of inboxFolder whose id is messageId
    move targetMessage to parentRef
  end tell
  return "OK"
end run

on split(s, delim)
  set AppleScript's text item delimiters to delim
  set outList to text items of s
  set AppleScript's text item delimiters to ""
  return outList
end split
