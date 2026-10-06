@echo off
title IntelliBI Lead Alert - Open port 8787 for counsellor PCs
REM ============================================================================
REM  Run on the OFFICE PC (right-click -> Run as administrator).
REM  Lets counsellor computers on the SAME local network reach the Lead Alert
REM  service on TCP 8787, whatever Windows calls the network (Public / Private /
REM  Domain). Root cause of 2026-10-06: the office Wi-Fi was "Public" while the
REM  rule only covered "Private", so every counsellor PC was silently blocked.
REM ============================================================================
net session >nul 2>&1
if errorlevel 1 (
    echo Please right-click this file and choose "Run as administrator".
    pause
    exit /b 1
)
set "RULE=IntelliBI Lead Alert 8787"
netsh advfirewall firewall show rule name="%RULE%" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="%RULE%" dir=in action=allow protocol=TCP localport=8787 profile=any remoteip=localsubnet,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
) else (
    netsh advfirewall firewall set rule name="%RULE%" new enable=yes profile=any remoteip=localsubnet,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
)
REM LAN discovery: counsellor apps find this PC again after its IP changes.
netsh advfirewall firewall delete rule name="IntelliBI Lead Alert discovery" >nul 2>&1
netsh advfirewall firewall add rule name="IntelliBI Lead Alert discovery" dir=in action=allow protocol=UDP localport=8788 profile=any remoteip=localsubnet,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
echo.
echo Current networks (any category is fine now):
powershell -NoProfile -Command "Get-NetConnectionProfile | Format-Table Name,NetworkCategory -AutoSize"
echo Rule:
powershell -NoProfile -Command "Get-NetFirewallRule -DisplayName '%RULE%' | Format-Table DisplayName,Enabled,Profile,Action -AutoSize"
echo Counsellors use:  http://^<this PC's IPv4^>:8787
ipconfig | findstr /c:"IPv4 Address"
pause
