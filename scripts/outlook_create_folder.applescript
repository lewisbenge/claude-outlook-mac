on run argv
  set folderName to item 1 of argv
  tell application "Microsoft Outlook"
    make new folder at default account with properties {name:folderName}
  end tell
  return "OK"
end run
