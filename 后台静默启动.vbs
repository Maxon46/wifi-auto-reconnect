' Win10 网卡自动重连 - 后台静默启动
' 双击此文件即可在后台启动（无命令行窗口）

Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

' 获取脚本所在目录
scriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)

' 启动 Python 脚本（隐藏命令行窗口）
WshShell.Run "pythonw """ & scriptDir & "\wifi_monitor.py""", 0, False

' 提示
MsgBox "Wi-Fi 自动重连工具已在后台启动！" & vbCrLf & vbCrLf & _
       "GUI 窗口将显示在桌面上，可最小化到任务栏。", vbInformation, "Wi-Fi 监控"