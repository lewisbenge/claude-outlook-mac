on run
  tell application "Microsoft Outlook"
    set accountRef to default account
    set sourceFolder to inbox of accountRef
    set topNames to {}
    repeat with f in folders of accountRef
      set end of topNames to (name of f)
    end repeat
    log "[debug] top-level folders: " & my join(topNames, ", ")

    set aiSorted to my ensureFolder(accountRef, "AI Sorted")
    set aiChildren to {}
    repeat with c in folders of aiSorted
      set end of aiChildren to (name of c)
    end repeat
    log "[debug] AI Sorted children: " & my join(aiChildren, ", ")

    set testFolder to my ensureFolder(aiSorted, "Test")
    log "[debug] ensured target folder: " & (name of testFolder)

    if (count of messages of sourceFolder) is 0 then
      return "[debug] Inbox empty; no move attempted"
    end if

    set testMessage to first message of sourceFolder
    log "[debug] test message subject: " & (subject of testMessage)
    move testMessage to testFolder
    log "[debug] move complete from " & (name of sourceFolder) & " to " & (name of testFolder)
  end tell
  return "OK"
end run

on ensureFolder(parentRef, folderName)
  tell application "Microsoft Outlook"
    try
      return folder folderName of parentRef
    on error
      return make new folder at parentRef with properties {name:folderName}
    end try
  end tell
end ensureFolder

on join(itemsList, delim)
  set AppleScript's text item delimiters to delim
  set outText to itemsList as text
  set AppleScript's text item delimiters to ""
  return outText
end join
