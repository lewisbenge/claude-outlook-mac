on run argv
  set messageId to item 1 of argv
  set targetFolderName to item 2 of argv
  tell application "Microsoft Outlook"
    set inboxFolder to inbox of default account
    set targetFolder to folder targetFolderName of default account
    set targetMessage to first message of inboxFolder whose id is messageId
    move targetMessage to targetFolder
  end tell
  return "OK"
end run
