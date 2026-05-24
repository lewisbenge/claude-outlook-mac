on run
  tell application "System Events"
    set isRunning to exists (processes where name is "Microsoft Outlook")
  end tell
  if not isRunning then
    tell application "Microsoft Outlook" to activate
    delay 1
  end if
  return "OK"
end run
