on run argv
  if (count of argv) is less than 2 then error "Missing args: message id and target path"
  set messageId to item 1 of argv
  set targetPath to item 2 of argv
  set leafName to my lastPathComponent(targetPath)

  tell application "Microsoft Outlook"
    set accountRef to default account
    set sourceFolder to inbox of accountRef
    log "[move] source folder: " & (name of sourceFolder)

    set aiSortedFolder to my ensureFolder(accountRef, "AI Sorted")
    set targetFolder to my ensureFolder(aiSortedFolder, leafName)

    log "[move] target folder requested: " & targetPath
    log "[move] resolved parent folder object: " & (name of aiSortedFolder)
    log "[move] resolved target folder object: " & (name of targetFolder)

    set targetMessage to missing value
    try
      set targetMessage to first message of sourceFolder whose id is messageId
      log "[move] message found by id: " & messageId
    on error errMsg number errNum
      log "[move] id lookup failed: " & errMsg & " (" & errNum & ")"
      set targetMessage to my findMessageBySubjectFallback(sourceFolder, messageId)
    end try

    if targetMessage is missing value then
      error "Unable to locate message by id or subject fallback. lookup key=" & messageId
    end if

    move targetMessage to targetFolder
    log "[move] moved message subject='" & (subject of targetMessage) & "' to folder='" & (name of targetFolder) & "'"
  end tell
  return "OK"
end run

on ensureFolder(parentRef, folderName)
  tell application "Microsoft Outlook"
    try
      set existingFolder to folder folderName of parentRef
      return existingFolder
    on error
      set createdFolder to make new folder at parentRef with properties {name:folderName}
      return createdFolder
    end try
  end tell
end ensureFolder

on findMessageBySubjectFallback(sourceFolder, lookupText)
  tell application "Microsoft Outlook"
    try
      set fallbackMessage to first message of sourceFolder whose subject contains lookupText
      log "[move] fallback subject lookup matched using text: " & lookupText
      return fallbackMessage
    on error errMsg number errNum
      log "[move] subject fallback failed: " & errMsg & " (" & errNum & ")"
      return missing value
    end try
  end tell
end findMessageBySubjectFallback

on lastPathComponent(pathText)
  set parts to my split(pathText, "/")
  if (count of parts) is 0 then return pathText
  return item (count of parts) of parts
end lastPathComponent

on split(s, delim)
  set AppleScript's text item delimiters to delim
  set outList to text items of s
  set AppleScript's text item delimiters to ""
  return outList
end split
