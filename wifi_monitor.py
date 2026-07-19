#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Win10 Pro 网卡自动重连工具
功能：24小时后台监控Wi-Fi连接状态，断开后自动重连，超过10次失败自动退出
"""

import subprocess
import threading
import time
import json
import os
import sys
import queue
import copy
from datetime import datetime
from tkinter import (
    Tk, Frame, Label, Button, Text, Scrollbar, Entry, StringVar,
    IntVar, Checkbutton, messagebox, ttk, VERTICAL, RIGHT, LEFT, BOTH,
    TOP, BOTTOM, X, Y, END, DISABLED, NORMAL, WORD, W, E, SUNKEN, HORIZONTAL,
    Toplevel
)

# ───────────────────── 版本信息 ─────────────────────
APP_VERSION = "v2.3"

CHANGELOG = [
    ("v2.3", "2026-07-14", [
        "修复手动关闭WLAN开关(无线电)后无法重连的问题",
        "ensure_wlan_enabled 升级为网卡+无线电双重检查",
        "检测radio关闭时自动尝试 netsh autoconfig + 重启网卡恢复",
        "smart_reconnect 扫描不到网络时自动重启网卡再扫描",
    ]),
    ("v2.2", "2026-07-14", [
        "基于水星MW150US网卡驱动分析，新增USB选择性挂起禁用功能",
        "新增网卡设备级重启(Disable/Enable-NetAdapter)，比netsh重连更彻底",
        "实现分阶段重试策略：标准重连(1-3次)→网卡重启(4-6次)→驱动重装(7-10次)",
        "新增WLANSvc服务自动重启保障",
        "修复扫描网络信号强度显示0%的问题(改用宽松正则匹配)",
        "修复已保存网络匹配为0个的问题(兼容中英文netsh输出)",
        "GUI新增USB节能优化、网卡重启阈值、驱动路径配置选项",
        "支持InstallShield静默重装驱动(/s参数)",
    ]),
    ("v2.1", "2026-07-14", [
        "重写WiFi信息获取函数，以Get-NetAdapter.Status作为连接状态权威判断",
        "修复连接状态误判(已断开却显示已连接)的问题",
        "优化检测逻辑：扫描可用网络并匹配已保存配置",
        "简化_check_connected函数，仅state=connected才判为已连接",
    ]),
    ("v2.0", "2026-07-13", [
        "更换主题风格为SaaS Blue + Orange配色方案",
        "新增网络延迟显示(ping baidu.com，PowerShell Test-Connection)",
        "延迟显示在网关旁边位置，每次检测都ping",
        "支持文件更新到指定目录(C:\\731电影\\wangkaxiangmu)",
        "启动脚本改为纯英文避免GBK/UTF-8编码冲突",
    ]),
    ("v1.3", "2026-07-13", [
        "修复GBK/UTF-8编码问题导致netsh输出解析失败",
        "修复网络延迟显示'--'的问题，改用PowerShell Test-Connection",
        "修复无法重连WiFi的问题，实现三级重连策略(PowerShell→cmd→netsh)",
        "引入smart_reconnect()智能匹配已保存网络",
        "修复f-string反斜杠转义语法错误",
    ]),
    ("v1.2", "2026-07-13", [
        "修复'当前Wi-Fi'显示'未连接'但实际已连接的bug",
        "修复netsh输出中'接收速率'包含'态'字覆盖'状态'字段的问题",
        "优化：网络显示'已连接'时不触发任何重新连接",
        "改用精确分割partition(':')并精确匹配key=='状态'",
    ]),
    ("v1.1", "2026-07-12", [
        "修复已连接网络时仍然触发重连的问题",
        "日志每隔30秒自动清空，避免日志堆积",
    ]),
    ("v1.0", "2026-07-12", [
        "初始版本发布",
        "24小时后台自动检测WiFi连接状态",
        "检测到断开后自动重连",
        "连续失败10次以上自动退出程序",
        "tkinter可视化中文管理界面",
    ]),
]


# ───────────────────── 配置 ─────────────────────
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wifi_monitor_config.json")
DEFAULT_CONFIG = {
    "max_retry": 10,
    "check_interval": 5,        # 检测间隔（秒）
    "reconnect_delay": 3,       # 重连间隔（秒）
    "target_ssid": "",           # 目标 Wi-Fi SSID（空=自动获取当前连接的）
    "minimize_to_tray": True,   # 关闭时最小化到托盘
    "auto_start": False,        # 启动时自动开始监控
    "disable_usb_suspend": True,  # 禁用 USB 选择性挂起
    "restart_adapter_after": 3,   # 连续失败 N 次后重启网卡
    "driver_exe_path": "",        # 驱动安装程序路径（水星 MW150US 等）
    "driver_iss_path": "",        # 静默安装响应文件 .iss 路径
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
        except Exception:
            return dict(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ───────────────────── Wi-Fi 操作 ─────────────────────
_NETSH_CANDIDATES = [
    "netsh",
    r"C:\Windows\System32\netsh.exe",
    r"C:\Windows\Sysnative\netsh.exe",
    r"C:\Windows\SysWOW64\netsh.exe",
]


def _find_netsh():
    """查找第一个可用的 netsh 可执行文件路径"""
    import shutil
    for path in _NETSH_CANDIDATES:
        if "\\" in path:
            if os.path.exists(path):
                return path
        else:
            found = shutil.which(path)
            if found:
                return found
    return None


def _find_all_netsh():
    """查找所有可用的 netsh 路径（按优先级排序，去重）"""
    import shutil
    paths = []
    seen = set()
    for path in _NETSH_CANDIDATES:
        real = None
        if "\\" in path:
            if os.path.exists(path):
                real = path
        else:
            found = shutil.which(path)
            if found:
                real = found
        if real and real.lower() not in seen:
            seen.add(real.lower())
            paths.append(real)
    return paths


def run_cmd(cmd, timeout=10):
    """执行 Windows 命令，自动适配编码，返回 (stdout, stderr, returncode)"""
    try:
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        # 先尝试 UTF-8，失败再用 GBK
        for enc in ("utf-8", "gbk", "gb2312", "cp936"):
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True,
                    timeout=timeout, encoding=enc, errors="strict",
                    startupinfo=startupinfo
                )
                out = (result.stdout or "").strip()
                err = (result.stderr or "").strip()
                return out, err, result.returncode
            except (UnicodeDecodeError, UnicodeError):
                continue
        # 最终兜底：replace 模式
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
            startupinfo=startupinfo
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        return out, err, result.returncode
    except subprocess.TimeoutExpired:
        return "", "命令超时", 1
    except FileNotFoundError as e:
        return "", f"找不到命令: {e}", 1
    except Exception as e:
        return "", f"{type(e).__name__}: {e}", 1


def _run_netsh(args, timeout=10):
    """执行 netsh 命令，自动尝试所有可用路径和调用方式"""
    all_paths = _find_all_netsh()
    if not all_paths:
        return "", "找不到 netsh.exe", 1

    best_out = ""
    best_err = ""
    best_code = 1

    for netsh_path in all_paths:
        # 方式1：直接调用
        cmd = [netsh_path] + args
        out1, err1, code1 = run_cmd(cmd, timeout=timeout)
        if code1 == 0 and out1:
            return out1, err1, code1
        if not best_out and (out1 or err1):
            best_out, best_err, best_code = out1, err1, code1

        # 方式2：cmd /c
        out2, err2, code2 = run_cmd(
            ["cmd", "/c", f"{netsh_path} " + " ".join(args)], timeout=timeout
        )
        if code2 == 0 and out2:
            return out2, err2, code2
        if not best_out and (out2 or err2):
            best_out, best_err, best_code = out2, err2, code2

        # 方式3：powershell
        out3, err3, code3 = run_cmd(
            ["powershell", "-NoProfile", "-Command", f"& '{netsh_path}' " + " ".join(args)],
            timeout=timeout
        )
        if code3 == 0 and out3:
            return out3, err3, code3
        if not best_out and (out3 or err3):
            best_out, best_err, best_code = out3, err3, code3

    return best_out, best_err, best_code


def _get_wifi_info_from_powershell():
    """
    通过 PowerShell 获取 Wi-Fi 信息
    以 Get-NetAdapter 的 Status 作为连接状态的权威判断
    返回 dict 或 None
    """
    ps_script = r'''
$ErrorActionPreference = 'SilentlyContinue'

# 第一步：找到无线网卡（最权威）
$adapter = Get-NetAdapter | Where-Object {
    $_.InterfaceDescription -match "Wireless|Wi-Fi|802.11|无线" -or
    $_.Name -match "WLAN|Wi-Fi|无线"
} | Select-Object -First 1

if (-not $adapter) {
    Write-Output "state:no_adapter"
    exit 0
}

Write-Output ("adapter_name:" + $adapter.Name)
Write-Output ("adapter_desc:" + $adapter.InterfaceDescription)
Write-Output ("adapter_status:" + $adapter.Status)

# 网卡被禁用
if ($adapter.Status -eq "Disabled") {
    Write-Output "state:disabled"
    exit 0
}

# 网卡断开状态（没有连接任何网络）
if ($adapter.Status -ne "Up") {
    Write-Output "state:disconnected"
    # 尝试获取无线网卡的详细信息（即使断开也可能有 netsh 输出）
    try {
        $lines = netsh wlan show interfaces 2>&1
        foreach ($line in $lines) {
            $line = $line.Trim()
            if (-not $line) { continue }
            if ($line -match "^SSID") {
                $parts = $line -split "[:：]", 2
                if ($parts.Count -ge 2 -and $parts[1].Trim()) {
                    Write-Output ("ssid:" + $parts[1].Trim())
                }
                continue
            }
        }
    } catch {}
    exit 0
}

# 网卡是 Up 状态，说明已连接
Write-Output "state:connected"

# 从 Get-NetConnectionProfile 获取 SSID
$wifi = Get-NetConnectionProfile | Where-Object {
    $_.InterfaceAlias -eq $adapter.Name -or
    $_.InterfaceAlias -match "wlan|wi-fi|无线"
} | Select-Object -First 1

if ($wifi) {
    Write-Output ("ssid:" + $wifi.Name)
    Write-Output ("profile:" + $wifi.Name)
}

# 获取速率
if ($adapter.LinkSpeed) {
    Write-Output ("tx_rate:" + $adapter.LinkSpeed)
}

# 通过 .NET API 获取 IP 信息
try {
    $interfaces = [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()
    foreach ($iface in $interfaces) {
        if ($iface.Name -eq $adapter.Name -or $iface.Description -eq $adapter.InterfaceDescription) {
            $props = $iface.GetIPProperties()
            foreach ($unicast in $props.UnicastAddresses) {
                if ($unicast.Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) {
                    Write-Output ("ipv4:" + $unicast.Address.ToString())
                }
            }
            foreach ($gateway in $props.GatewayAddresses) {
                if ($gateway.Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) {
                    Write-Output ("gateway:" + $gateway.Address.ToString())
                    break
                }
            }
        }
    }
} catch {}

# 通过 netsh 管道获取信号、信道、BSSID
try {
    $lines = netsh wlan show interfaces 2>&1
    foreach ($line in $lines) {
        $line = $line.Trim()
        if (-not $line) { continue }
        if ($line -match "^(信号|Signal)") {
            $parts = $line -split "[:：]", 2
            if ($parts.Count -ge 2) { Write-Output ("signal:" + $parts[1].Trim()); continue }
        }
        if ($line -match "^(信道|Channel)") {
            $parts = $line -split "[:：]", 2
            if ($parts.Count -ge 2) { Write-Output ("channel:" + $parts[1].Trim()); continue }
        }
        if ($line -match "^BSSID") {
            $parts = $line -split "[:：]", 2
            if ($parts.Count -ge 2) { Write-Output ("bssid:" + $parts[1].Trim()); continue }
        }
        if ($line -match "^(SSID)") {
            $parts = $line -split "[:：]", 2
            if ($parts.Count -ge 2 -and $parts[1].Trim()) {
                # 只有 ssid 还没设才用 netsh 的
                if (-not $wifi) { Write-Output ("ssid:" + $parts[1].Trim()) }
                continue
            }
        }
        if ($line -match "^(Profile|配置文件)") {
            $parts = $line -split "[:：]", 2
            if ($parts.Count -ge 2 -and $parts[1].Trim()) {
                if (-not $wifi) { Write-Output ("profile:" + $parts[1].Trim()) }
                continue
            }
        }
        if ($line -match "^(接收速率|Transmit rate|Tx Rate)") {
            $parts = $line -split "[:：]", 2
            if ($parts.Count -ge 2 -and $parts[1].Trim()) {
                Write-Output ("tx_rate:" + $parts[1].Trim())
                continue
            }
        }
    }
} catch {}
'''
    out, err, code = run_cmd(
        ["powershell", "-NoProfile", "-Command", ps_script], timeout=20
    )
    if code != 0 and not out:
        return None

    info = {}
    for line in out.split("\n"):
        line = line.strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip()
        if not val:
            continue
        # 避免后面的值覆盖前面的（保持第一个出现的值）
        if key not in info:
            info[key] = val

    info.setdefault("state", "disconnected")
    return info


def _get_wifi_info_from_netsh():
    """通过 netsh (文本解析) 获取 Wi-Fi 信息，返回 dict 或 None"""
    stdout, stderr, code = _run_netsh(["wlan", "show", "interfaces"])
    if code != 0 or not stdout:
        return None

    info = {}
    for line in stdout.split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue

        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if not val:
            continue

        if key == "SSID" and "BSSID" not in line:
            info["ssid"] = val
        elif key in ("状态", "State", "state"):
            info["state"] = val.lower()
        elif key in ("名称", "Name", "name"):
            info["name"] = val
        elif key in ("信号", "Signal", "signal"):
            info["signal"] = val
        elif key in ("信道", "Channel", "channel"):
            info["channel"] = val
        elif key in ("传输速率 (Mbps)", "传输速率(Mbps)", "Transmit rate (Mbps)"):
            info["tx_rate"] = val
        elif key in ("接收速率(Mbps)", "Receive rate (Mbps)"):
            info["rx_rate"] = val
        elif key in ("配置文件", "Profile", "profile"):
            info["profile"] = val
        elif key in ("描述", "Description", "description"):
            info["desc"] = val

    return info


def get_current_wifi_info():
    """获取当前 Wi-Fi 连接信息（PowerShell 优先，netsh 兜底）"""
    # 方式1：PowerShell（最可靠）
    info = _get_wifi_info_from_powershell()
    if info:
        return info

    # 方式2：netsh 文本解析
    return _get_wifi_info_from_netsh()


def is_wifi_connected():
    """检查 Wi-Fi 是否已连接（兼容中/英文 Windows）"""
    info = get_current_wifi_info()
    if not info:
        return False, ""

    state = info.get("state", "")
    ssid = info.get("ssid", "")

    # 状态字段匹配：已连接 / connected / 已連線
    connected_keywords = ("已连接", "connected", "已連線")
    if any(kw in state for kw in connected_keywords):
        return True, ssid

    # 兜底：SSID 不为空且状态不含断开关键字 → 视为已连接
    disconnect_keywords = ("断开", "disconnect", "已断开")
    if ssid and not any(kw in state for kw in disconnect_keywords):
        return True, ssid

    return False, ""


def get_saved_profiles():
    """获取系统中所有已保存的 Wi-Fi 配置文件名称列表（PowerShell 管道内执行 netsh）"""
    ps_script = r'''
$ErrorActionPreference = "SilentlyContinue"
$output = netsh wlan show profiles 2>&1 | Out-String
$names = @()
$lines = $output -split "`r?`n"
$in_section = $false
foreach ($line in $lines) {
    $line = $line.Trim()
    if ($line -match "用户配置文件|All User Profile|所有用户配置文件") {
        $in_section = $true
        continue
    }
    if ($in_section -and $line -match ":\s*(.+)$") {
        $name = $matches[1].Trim()
        if ($name -and $name -notmatch "^\d+$") {
            $names += $name
        }
    }
}
if ($names.Count -eq 0) {
    foreach ($line in $lines) {
        if ($line -match "^\s*([^:\s]+.*?)\s*:\s*(.+)$") {
            $val = $matches[2].Trim()
            if ($val -and $val -notmatch "^\d+$" -and $val -notmatch "^[A-Z]:\\" -and $line -notmatch "接口|Interface|名称|Name") {
                $names += $val
            }
        }
    }
}
$names -join "`n"
'''
    stdout, stderr, code = run_cmd(
        ["powershell", "-NoProfile", "-Command", ps_script],
        timeout=15
    )
    if code != 0 or not stdout.strip():
        return []
    names = [l.strip() for l in stdout.strip().split("\n") if l.strip() and len(l.strip()) > 1]
    # 去重
    seen = set()
    result = []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            result.append(n)
    return result


def scan_available_networks():
    """扫描当前可用的 Wi-Fi 网络，返回 [(ssid, signal_percent), ...]，按信号从强到弱排序（PowerShell 管道）"""
    ps_script = r'''
$ErrorActionPreference = "SilentlyContinue"
netsh wlan show networks mode=bssid 2>&1 | Out-Null
Start-Sleep -Milliseconds 800
$output = netsh wlan show networks mode=bssid 2>&1 | Out-String
$lines = $output -split "`r?`n"
$nets = @()
$current_ssid = $null
$current_signal = 0
foreach ($line in $lines) {
    $line = $line.Trim()
    if ($line -match "^SSID\s*\d*\s*:\s*(.+)$") {
        if ($current_ssid) { $nets += ,@($current_ssid, [int]$current_signal) }
        $current_ssid = $matches[1].Trim()
        $current_signal = 0
    } elseif ($line -match "(\d+)\s*%") {
        $sig = [int]$matches[1]
        if ($sig -gt 0 -and $sig -le 100) {
            $current_signal = $sig
        }
    }
}
if ($current_ssid) { $nets += ,@($current_ssid, [int]$current_signal) }
$nets = $nets | Sort-Object { $_[1] } -Descending
foreach ($n in $nets) { Write-Output "$($n[0])|$($n[1])" }
'''
    stdout, stderr, code = run_cmd(
        ["powershell", "-NoProfile", "-Command", ps_script],
        timeout=20
    )
    if code != 0 or not stdout.strip():
        return []
    result = []
    for line in stdout.strip().split("\n"):
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|", 1)
        ssid = parts[0].strip()
        try:
            sig = int(parts[1].strip())
        except ValueError:
            sig = 0
        if ssid:
            result.append((ssid, sig))
    return result


def ensure_wlan_enabled():
    """确保 WLAN 接口已启用且无线开关（radio）打开，返回 (是否成功, 说明)"""
    ps_check = r'''
$ErrorActionPreference = "SilentlyContinue"
$adapters = Get-NetAdapter -Name "*wlan*","*wi-fi*","*无线*" -ErrorAction SilentlyContinue
if (-not $adapters) { Write-Output "NO_ADAPTER"; exit }
$adapter = $adapters | Select-Object -First 1
$name = $adapter.Name
$status = $adapter.Status
Write-Output "NAME:$name"
Write-Output "STATUS:$status"
if ($status -eq "Disabled") {
    Write-Output "STATE:DISABLED"
    exit
}
# 用 netsh 接口信息快速判断 radio 状态（比扫描快）
$iface = netsh wlan show interfaces 2>&1 | Out-String
if ($iface -match "无线电状态.*关闭|Radio.*Off|radio.*off") {
    Write-Output "STATE:RADIO_OFF"
} elseif ($iface -match "SSID\s*:") {
    Write-Output "STATE:RADIO_ON"
} else {
    # 拿不准，扫一下确认
    $scan = netsh wlan show networks mode=bssid 2>&1 | Out-String
    if ($scan -match "SSID\s*\d*\s*:") {
        Write-Output "STATE:RADIO_ON"
    } else {
        Write-Output "STATE:RADIO_OFF"
    }
}
'''
    stdout, _, code = run_cmd(
        ["powershell", "-NoProfile", "-Command", ps_check],
        timeout=15
    )
    if "NO_ADAPTER" in stdout:
        return False, "未找到无线网卡"

    if "STATE:DISABLED" in stdout:
        # 网卡被禁用，先启用
        ps_enable = r'''
$ErrorActionPreference = "SilentlyContinue"
$adapters = Get-NetAdapter -Name "*wlan*","*wi-fi*","*无线*" -ErrorAction SilentlyContinue
if (-not $adapters) { Write-Output "FAIL"; exit }
$adapters | Enable-NetAdapter -Confirm:$false -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$a2 = Get-NetAdapter -Name "*wlan*","*wi-fi*","*无线*" -ErrorAction SilentlyContinue
$ok = $false
foreach ($a in $a2) { if ($a.Status -ne "Disabled") { $ok = $true; break } }
if ($ok) { Write-Output "OK" } else { Write-Output "FAIL" }
'''
        stdout2, _, _ = run_cmd(
            ["powershell", "-NoProfile", "-Command", ps_enable],
            timeout=15
        )
        if "OK" not in stdout2:
            return False, "无法启用 WLAN 网卡"

    # 检查 radio 是否打开
    if "STATE:RADIO_OFF" in stdout:
        # 先尝试用 netsh 打开 autoconfig
        run_cmd(["netsh", "wlan", "set", "autoconfig", "enabled=yes"], timeout=10)
        time.sleep(1)
        # 再试一次扫描
        test_scan = scan_available_networks()
        if test_scan:
            return True, "WLAN 无线电已打开"
        # 还是不行，重启网卡
        ok, msg = restart_wifi_adapter()
        if ok:
            time.sleep(5)
            return True, "重启网卡后 WLAN 已恢复"
        return False, f"WLAN 无线电关闭，{msg}"

    return True, "WLAN 已启用且无线电正常"


def smart_reconnect(preferred_ssid=None, adapter_name=None):
    """
    智能重连：
    1. 确保 WLAN 接口启用
    2. 获取已保存的配置文件
    3. 扫描可用网络
    4. 扫描不到时自动重启网卡再扫（处理 WLAN 开关被手动关闭的情况）
    5. 匹配「可用 + 已保存」的网络，优先首选 SSID，其次按信号强度
    6. 逐个尝试连接
    返回 (是否成功, 连接的 SSID, 详细日志)
    """
    logs = []

    # 步骤 1：确保 WLAN 启用
    ok, msg = ensure_wlan_enabled()
    logs.append(f"[WLAN] {msg}")
    if not ok:
        return False, "", "\n".join(logs)

    # 步骤 2：获取已保存的配置文件
    saved = get_saved_profiles()
    saved_lower = [s.lower() for s in saved]
    logs.append(f"[已保存] 共 {len(saved)} 个: {', '.join(saved[:5])}{'...' if len(saved) > 5 else ''}")

    # 步骤 3：扫描可用网络
    available = scan_available_networks()
    logs.append(f"[可用] 共 {len(available)} 个网络")

    # 步骤 3.5：扫描不到 → 重启网卡再扫（处理 WLAN 开关被手动关闭的情况）
    if not available:
        logs.append("扫描不到网络，尝试重启网卡重新打开 WLAN 无线电...")
        r_ok, r_msg = restart_wifi_adapter(adapter_name)
        logs.append(f"  {r_msg}")
        if r_ok:
            time.sleep(6)
            available2 = scan_available_networks()
            logs.append(f"  重启后扫描到 {len(available2)} 个网络")
            if available2:
                available = available2

    if not available:
        logs.append("仍扫描不到任何可用 Wi-Fi 网络")
        return False, "", "\n".join(logs)

    # 步骤 4：匹配可用 + 已保存
    matched = []  # [(ssid, signal, profile_name)]
    for ssid, sig in available:
        if not ssid:
            continue
        # 在已保存列表中精确匹配 SSID（大小写不敏感）
        for i, s in enumerate(saved_lower):
            if s == ssid.lower():
                matched.append((ssid, sig, saved[i]))
                break

    logs.append(f"[匹配] 可用且已保存的网络: {len(matched)} 个")
    if not matched:
        # 如果没有匹配的，就用所有可用的尝试连接（万一 profile 名不同）
        logs.append("无精确匹配，尝试所有可用网络...")
        matched = [(ssid, sig, ssid) for ssid, sig in available]

    # 步骤 5：如果有首选 SSID，把它排到最前面
    if preferred_ssid:
        preferred_lower = preferred_ssid.lower()
        matched.sort(key=lambda x: (0 if x[0].lower() == preferred_lower else 1, -x[1]))
    else:
        matched.sort(key=lambda x: -x[1])

    # 步骤 6：逐个尝试连接
    for ssid, sig, profile_name in matched:
        logs.append(f"[尝试] {ssid} (信号 {sig}%) ...")
        success, output = _connect_by_profile(profile_name)
        if success:
            logs.append(f"[成功] 已连接到: {ssid}")
            return True, ssid, "\n".join(logs)
        else:
            logs.append(f"[失败] {ssid}: {str(output)[:100]}")

    return False, "", "\n".join(logs)


def _connect_by_profile(profile_name):
    """用配置文件名称连接 Wi-Fi（PowerShell 管道执行 netsh）"""
    safe_name = profile_name.replace("'", "''")
    ps_script = (
        '$ErrorActionPreference = "Continue"; '
        '$name = \'' + safe_name + '\'; '
        'netsh wlan connect name=$name 2>&1 | Out-Null; '
        'if ($LASTEXITCODE -eq 0) { Write-Output "OK" } else { Write-Output "FAIL" }'
    )
    stdout, stderr, code = run_cmd(
        ["powershell", "-NoProfile", "-Command", ps_script],
        timeout=15
    )
    if "OK" in stdout:
        return True, stdout
    # 备用：cmd /c
    stdout2, stderr2, code2 = run_cmd(
        ["cmd", "/c", 'netsh wlan connect name="' + profile_name + '" && echo OK || echo FAIL'],
        timeout=15
    )
    if "OK" in stdout2:
        return True, stdout2
    return False, (stdout or stderr or stdout2 or stderr2)


def get_available_networks():
    """获取可用 Wi-Fi 列表（兼容旧接口，内部用 scan_available_networks）"""
    nets = scan_available_networks()
    return [ssid for ssid, _ in nets]


def connect_wifi(ssid_or_profile):
    """连接指定 Wi-Fi（支持 SSID 或配置文件名称），返回 (成功, 输出)"""
    if not ssid_or_profile:
        return False, "SSID 为空"

    # 用 PowerShell 执行 netsh wlan connect（绕过直接调 netsh 返回空的问题）
    # 脚本始终输出 "OK" 或 "FAIL"，不依赖 netsh 的 stdout
    ps_script = (
        f'$ErrorActionPreference = "Continue"; '
        f'netsh wlan connect name="{ssid_or_profile}" 2>&1 | Out-Null; '
        f'if ($LASTEXITCODE -eq 0) {{ Write-Output "OK" }} else {{ Write-Output "FAIL" }}'
    )
    stdout, stderr, code = run_cmd(
        ["powershell", "-NoProfile", "-Command", ps_script],
        timeout=15
    )
    if "OK" in stdout:
        return True, stdout

    # 备用：cmd /c + 检查退出码
    stdout2, stderr2, code2 = run_cmd(
        ["cmd", "/c", f"netsh wlan connect name=\"{ssid_or_profile}\" && echo OK || echo FAIL"],
        timeout=15
    )
    if "OK" in stdout2:
        return True, stdout2

    return False, (stdout or stderr or stdout2 or stderr2)


def disconnect_wifi():
    """断开当前 Wi-Fi"""
    stdout, stderr, code = _run_netsh(["wlan", "disconnect"])
    return code == 0


def check_internet():
    """检查互联网连通性（ping baidu.com 用 PowerShell），返回 (是否连通, 延迟ms)"""
    # 用 PowerShell Test-Connection 获取延迟，避免中文编码解析问题
    stdout, stderr, code = run_cmd(
        ["powershell", "-NoProfile", "-Command",
         "try { $r = Test-Connection baidu.com -Count 1 -ErrorAction Stop; Write-Output $r.ResponseTime } catch { Write-Output 'FAIL' }"],
        timeout=8
    )
    if code != 0 or not stdout or "FAIL" in stdout:
        return False, ""
    try:
        ms = int(float(stdout.strip()))
        return True, f"{ms} ms"
    except ValueError:
        return False, ""


def ping_latency():
    """快速 ping baidu.com 获取延迟（毫秒），失败返回空字符串"""
    _, latency = check_internet()
    return latency


def get_raw_wifi_output():
    """获取 netsh 原始输出（用于诊断），返回 (stdout, stderr, code, netsh_path)"""
    netsh_path = _find_netsh()
    stdout, stderr, code = _run_netsh(["wlan", "show", "interfaces"])
    return stdout, stderr, code, netsh_path


def check_wlan_service():
    """检查 WLAN AutoConfig 服务状态"""
    stdout, stderr, code = run_cmd(["sc", "query", "Wlansvc"])
    if code != 0:
        return "未知"
    for line in stdout.split("\n"):
        if "STATE" in line and "RUNNING" in line.upper():
            return "运行中"
        if "STATE" in line and "STOPPED" in line.upper():
            return "已停止"
    return "未知"


def ensure_wlan_service_running():
    """确保 WLAN AutoConfig 服务正在运行，已停止则自动启动，返回 (是否正常, 描述)"""
    status = check_wlan_service()
    if status == "运行中":
        return True, "WLAN 服务运行中"
    # 尝试启动服务
    stdout, stderr, code = run_cmd(["net", "start", "Wlansvc"], timeout=30)
    time.sleep(2)
    status2 = check_wlan_service()
    if status2 == "运行中":
        return True, "WLAN 服务已重新启动"
    return False, f"WLAN 服务启动失败: {status2}"


def get_wifi_adapter_name():
    """获取无线网卡的名称（用于 Disable/Enable-NetAdapter），返回名称或空字符串"""
    ps_script = r'''
$ErrorActionPreference = "SilentlyContinue"
$adapter = Get-NetAdapter | Where-Object {
    $_.InterfaceDescription -match "Wireless|Wi-Fi|802.11|无线|Mercury|MW150" -or
    $_.Name -match "WLAN|Wi-Fi|无线"
} | Select-Object -First 1
if ($adapter) { Write-Output $adapter.Name } else { Write-Output "" }
'''
    stdout, _, code = run_cmd(
        ["powershell", "-NoProfile", "-Command", ps_script],
        timeout=10
    )
    return stdout.strip()


def restart_wifi_adapter(adapter_name=None):
    """
    重启无线网卡设备（禁用→启用），比单纯 netsh 重连更彻底，能重置驱动状态
    返回 (是否成功, 描述)
    """
    if not adapter_name:
        adapter_name = get_wifi_adapter_name()
    if not adapter_name:
        return False, "未找到无线网卡"

    ps_script = r'''
$ErrorActionPreference = "Continue"
$name = ''' + "'" + adapter_name.replace("'", "''") + "'" + r'''
try {
    Disable-NetAdapter -Name $name -Confirm:$false -ErrorAction Stop
    Start-Sleep -Seconds 3
    Enable-NetAdapter -Name $name -Confirm:$false -ErrorAction Stop
    Start-Sleep -Seconds 5
    Write-Output "OK"
} catch {
    Write-Output "FAIL: $($_.Exception.Message)"
}
'''
    stdout, stderr, code = run_cmd(
        ["powershell", "-NoProfile", "-Command", ps_script],
        timeout=30
    )
    if "OK" in stdout:
        return True, f"网卡 {adapter_name} 已重启"
    return False, f"网卡重启失败: {stdout[:100]}"


def disable_usb_selective_suspend():
    """
    禁用 USB 选择性挂起（防止 Windows 省电导致 USB 网卡断连）
    仅修改注册表，需要管理员权限，返回 (是否成功, 描述)
    """
    ps_script = r'''
$ErrorActionPreference = "Continue"
try {
    $key = "HKLM:\SYSTEM\CurrentControlSet\Services\USB"
    if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
    Set-ItemProperty -Path $key -Name "DisableSelectiveSuspend" -Value 1 -Type DWord -Force
    Write-Output "OK"
} catch {
    Write-Output "FAIL: $($_.Exception.Message)"
}
'''
    stdout, stderr, code = run_cmd(
        ["powershell", "-NoProfile", "-Command", ps_script],
        timeout=10
    )
    if "OK" in stdout:
        return True, "已禁用 USB 选择性挂起"
    return False, f"设置失败（可能需要管理员权限）: {stdout[:100]}"


def check_usb_selective_suspend():
    """检查 USB 选择性挂起是否已禁用，返回 (已禁用, 当前值)"""
    ps_script = r'''
$ErrorActionPreference = "SilentlyContinue"
$val = Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\USB" -Name "DisableSelectiveSuspend" -ErrorAction SilentlyContinue
if ($val) { Write-Output $val.DisableSelectiveSuspend } else { Write-Output "NOT_SET" }
'''
    stdout, _, code = run_cmd(
        ["powershell", "-NoProfile", "-Command", ps_script],
        timeout=10
    )
    val = stdout.strip()
    if val == "1":
        return True, "已禁用"
    if val == "0":
        return False, "已启用(0)"
    return False, "未设置"


def reinstall_driver_silent(exe_path, iss_path="", log_path=""):
    """
    使用 InstallShield 静默模式重装驱动（水星 MW150US 免驱版）
    返回 (是否成功, 描述)
    """
    import os
    if not exe_path or not os.path.exists(exe_path):
        return False, f"驱动安装程序不存在: {exe_path}"

    cmd_parts = [f'"{exe_path}"', "/s"]
    if iss_path and os.path.exists(iss_path):
        cmd_parts.append(f'/f1"{iss_path}"')
    if log_path:
        cmd_parts.append(f'/f2"{log_path}"')

    cmd = " ".join(cmd_parts)
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, timeout=120
        )
        if result.returncode == 0:
            return True, "驱动重装成功"
        return False, f"驱动重装返回码: {result.returncode}"
    except Exception as e:
        return False, f"驱动重装异常: {e}"


# ───────────────────── 监控线程 ─────────────────────
class MonitorThread(threading.Thread):
    def __init__(self, config, log_queue):
        super().__init__(daemon=True)
        self.config = copy.deepcopy(config)
        self.log_queue = log_queue
        self._stop_event = threading.Event()
        self._paused = False
        self.retry_count = 0
        self.total_reconnects = 0
        self.status = "已停止"
        self.last_ssid = ""              # 断开前记住的 SSID，用于回退
        self.last_profile = ""           # 断开前记住的配置文件名称
        self.last_interface = ""         # 网卡接口名称
        # GUI 直接读取的属性（线程安全，仅本线程写入）
        self.current_ssid = ""           # 当前 Wi-Fi SSID
        self.is_connected = False        # 是否已连接
        self.signal = ""                 # 信号强度
        self.channel = ""                # 信道
        self.tx_rate = ""                # 传输速率
        self.rx_rate = ""                # 接收速率
        self.ipv4 = ""                   # IPv4 地址
        self.gateway = ""                # 网关
        self.ping_ms = ""                # 网络延迟

    def log(self, msg, level="INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(("LOG", f"[{ts}] [{level}] {msg}"))

    def _sync_status_from_info(self, info, connected):
        """从 info 字典同步所有状态字段"""
        if connected and info:
            self.current_ssid = info.get("ssid", "")
            self.is_connected = True
            self.signal = info.get("signal", "")
            self.channel = info.get("channel", "")
            self.tx_rate = info.get("tx_rate", "")
            self.rx_rate = info.get("rx_rate", "")
            self.ipv4 = info.get("ipv4", "")
            self.gateway = info.get("gateway", "")
            # 记住关键信息供重连用
            if info.get("ssid"):
                self.last_ssid = info["ssid"]
            if info.get("profile"):
                self.last_profile = info["profile"]
            if info.get("name"):
                self.last_interface = info["name"]
        else:
            self.current_ssid = ""
            self.is_connected = False
            self.signal = ""
            self.channel = ""
            self.tx_rate = ""
            self.rx_rate = ""
            self.ipv4 = ""
            self.gateway = ""
            self.ping_ms = ""

    @staticmethod
    def _check_connected(info):
        """从 info 字典判断是否已连接，返回 (connected, ssid)"""
        if not info:
            return False, ""
        state = info.get("state", "")
        ssid = info.get("ssid", "")
        # state 为 "connected" 或 "up" 时认为已连接
        if state in ("connected", "up", "已连接"):
            return True, ssid
        return False, ""

    def stop(self):
        self._stop_event.set()
        self.status = "已停止"

    def pause(self):
        self._paused = True
        self.status = "已暂停"

    def resume(self):
        self._paused = False
        self.status = "运行中"

    def run(self):
        self.status = "运行中"
        self.log("Wi-Fi 监控已启动")
        self.log(f"检测间隔: {self.config['check_interval']}秒 | 最大重试: {self.config['max_retry']}次")

        # 启动时禁用 USB 选择性挂起（防止 USB 网卡因省电断连）
        if self.config.get("disable_usb_suspend", True):
            usb_ok, usb_msg = disable_usb_selective_suspend()
            self.log(f"[优化] {usb_msg}", "INFO" if usb_ok else "WARN")

        # 确保 WLAN 服务正常
        svc_ok, svc_msg = ensure_wlan_service_running()
        self.log(f"[服务] {svc_msg}", "INFO" if svc_ok else "WARN")

        # 启动时立即检测一次当前状态
        info = get_current_wifi_info()
        connected, ssid = self._check_connected(info)
        self._sync_status_from_info(info, connected)
        if connected:
            self.log(f"当前已连接 Wi-Fi: {ssid}，进入监听模式（仅检测，不重连）", "SUCCESS")
        else:
            self.log("当前未连接 Wi-Fi，开始监控…", "WARN")

        while not self._stop_event.is_set():
            if self._paused:
                time.sleep(1)
                continue

            try:
                info = get_current_wifi_info()
                connected, ssid = self._check_connected(info)

                # ── 已连接：仅检测，不触发任何重连 ──
                if connected:
                    self._sync_status_from_info(info, True)
                    if self.retry_count > 0:
                        self.log(f"✓ 重连成功！当前连接: {ssid}", "SUCCESS")
                        self.retry_count = 0
                    # 每次检测都 ping 百度测延迟
                    ok, lat = check_internet()
                    self.ping_ms = lat if ok else "超时"
                    signal_str = self.signal or "--"
                    self.log(f"检测: {ssid} | 信号: {signal_str} | 延迟: {self.ping_ms}", "INFO")
                    time.sleep(self.config["check_interval"])
                    continue

                # ── 检测到断开，二次确认 ──
                self._sync_status_from_info(info, False)
                self.ping_ms = "超时"
                self.log("检测: Wi-Fi 已断开 | 延迟: 超时", "WARN")
                time.sleep(1)
                info2 = get_current_wifi_info()
                connected2, ssid2 = self._check_connected(info2)
                if connected2:
                    self._sync_status_from_info(info2, True)
                    self.log(f"网络已恢复，无需重连（当前连接: {ssid2}）", "INFO")
                    if self.retry_count > 0:
                        self.retry_count = 0
                    time.sleep(self.config["check_interval"])
                    continue

                # ── 确认断开，开始分阶段智能重连 ──
                self.retry_count += 1
                self.total_reconnects += 1
                restart_after = self.config.get("restart_adapter_after", 3)
                driver_exe = self.config.get("driver_exe_path", "")
                driver_iss = self.config.get("driver_iss_path", "")

                # 阶段 1 (1~N次): 标准 netsh 重连
                # 阶段 2 (N+1~N+3次): 重启网卡设备
                # 阶段 3 (N+4~max): 重装驱动（仅配置了驱动路径时）
                stage = 1
                if self.retry_count > restart_after:
                    stage = 2
                if self.retry_count > restart_after + 3 and driver_exe:
                    stage = 3

                stage_names = {1: "标准重连", 2: "网卡重启", 3: "驱动重装"}
                self.log(f"✗ 检测到 Wi-Fi 断开！第 {self.retry_count} 次尝试 [{stage_names.get(stage, '?')}]", "WARN")

                # ── 阶段 2：重启网卡 ──
                if stage == 2:
                    self.log("[阶段2] 标准重连多次失败，尝试重启网卡设备...", "INFO")
                    ok, msg = restart_wifi_adapter(self.last_interface or None)
                    self.log(f"  {msg}", "INFO")
                    if ok:
                        time.sleep(5)  # 等待网卡启动和扫描

                # ── 阶段 3：重装驱动 ──
                if stage == 3:
                    self.log("[阶段3] 网卡重启无效，尝试静默重装驱动...", "INFO")
                    log_path = os.path.join(os.path.dirname(CONFIG_FILE), "driver_reinstall.log")
                    ok, msg = reinstall_driver_silent(driver_exe, driver_iss, log_path)
                    self.log(f"  {msg}", "INFO")
                    if ok:
                        time.sleep(15)  # 等待驱动安装完成和设备重启

                # 始终确保 WLAN 服务正常
                svc_ok, svc_msg = ensure_wlan_service_running()
                if not svc_ok:
                    self.log(f"  ⚠ {svc_msg}", "WARN")

                # 首选 SSID：用户设置的 > 上次连接的 SSID
                preferred = self.config["target_ssid"] or self.last_ssid or self.last_profile
                self.log(f"智能重连: 首选={preferred or '无(按信号最强)'}, 开始扫描匹配...", "INFO")

                success, connected_ssid, detail_log = smart_reconnect(
                    preferred_ssid=preferred, adapter_name=self.last_interface or None)

                # 输出详细日志
                for line in detail_log.split("\n"):
                    if line.strip():
                        self.log(f"  {line}", "INFO")

                if success:
                    # 等待连接稳定
                    time.sleep(self.config["reconnect_delay"])
                    info3 = get_current_wifi_info()
                    c, s = self._check_connected(info3)
                    if c:
                        self._sync_status_from_info(info3, True)
                        self.log(f"✓ 重连成功！已连接到: {s}", "SUCCESS")
                        self.retry_count = 0
                    else:
                        self.log(f"连接命令已执行，等待生效…", "INFO")
                else:
                    self.log(f"重连失败，等待下次重试...", "ERROR")

                if self.retry_count >= self.config["max_retry"]:
                    self.log(f"⛔ 已达到最大重试次数 ({self.config['max_retry']})，自动停止监控！", "CRITICAL")
                    self.status = "已停止（超限）"
                    self.current_ssid = ""
                    self.is_connected = False
                    self._stop_event.set()
                    break

            except Exception as e:
                self.log(f"监控异常: {e}", "ERROR")

            time.sleep(self.config["check_interval"])

        self.log("Wi-Fi 监控已停止")


# ───────────────────── GUI ─────────────────────
class WiFiMonitorApp:
    def __init__(self):
        self.config = load_config()
        self.monitor = None
        self.log_queue = queue.Queue()
        self._stopped_handled = False   # 防止重复调用 _on_monitor_stopped

        # 主窗口
        self.root = Tk()
        self.root.title(f"Wi-Fi 自动重连管理工具 {APP_VERSION}")
        self.root.geometry("720x640")
        self.root.minsize(640, 560)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 样式
        self._setup_style()
        self._build_ui()

        # 定时刷新日志
        self._poll_log()

        # 每隔 30 秒自动清空日志
        self._auto_clear_log()

        # 启动时是否自动开始
        if self.config.get("auto_start"):
            self.root.after(500, self.start_monitor)

    # ── 样式 ──
    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Microsoft YaHei", 14, "bold"))
        style.configure("Status.TLabel", font=("Microsoft YaHei", 11))
        style.configure("TButton", font=("Microsoft YaHei", 10), padding=6)
        style.configure("TLabel", font=("Microsoft YaHei", 10))
        style.configure("TCheckbutton", font=("Microsoft YaHei", 10))
        bg = "#F8FAFC"
        self.root.configure(bg=bg)

    # ── UI 构建 ──
    def _build_ui(self):
        # SaaS Blue + Orange 配色方案
        COLORS = {
            "bg": "#F8FAFC",
            "card": "#FFFFFF",
            "card_border": "#E2E8F0",
            "text": "#1E293B",
            "text_secondary": "#64748B",
            "primary": "#2563EB",
            "primary_dark": "#1E40AF",
            "cta": "#F97316",
            "success": "#22C55E",
            "danger": "#DC2626",
            "warning": "#F59E0B",
            "info": "#06B6D4",
            "status_bg": "#EFF6FF",
        }

        # ─── 标题栏 ───
        title_frame = Frame(self.root, bg=COLORS["primary_dark"], height=52)
        title_frame.pack(fill=X)
        title_frame.pack_propagate(False)
        Label(
            title_frame, text=f"Wi-Fi 自动重连管理工具  {APP_VERSION}",
            bg=COLORS["primary_dark"], fg="white", font=("Microsoft YaHei", 14, "bold")
        ).pack(side=LEFT, expand=True)
        Button(
            title_frame, text="更新日志", command=self.show_changelog,
            bg=COLORS["cta"], fg="white", font=("Microsoft YaHei", 9),
            relief="flat", padx=10, pady=2, cursor="hand2"
        ).pack(side=RIGHT, padx=10)

        # ─── 主内容区域 ───
        main_frame = Frame(self.root, bg=COLORS["bg"])
        main_frame.pack(fill=BOTH, expand=True, padx=15, pady=10)

        # ── 状态面板 ──
        status_frame = Frame(main_frame, bg=COLORS["card"], relief=SUNKEN, bd=1)
        status_frame.pack(fill=X, pady=(0, 10))

        self.status_var = StringVar(value="就绪")
        self.retry_var = StringVar(value="0")
        self.total_var = StringVar(value="0")
        self.wifi_var = StringVar(value="--")
        self.signal_var = StringVar(value="--")
        self.channel_var = StringVar(value="--")
        self.tx_rate_var = StringVar(value="--")
        self.ipv4_var = StringVar(value="--")
        self.gateway_var = StringVar(value="--")

        # 左列
        left_items = [
            ("监控状态:", self.status_var, COLORS["primary"]),
            ("当前 Wi-Fi:", self.wifi_var, COLORS["success"]),
            ("当前重试次数:", self.retry_var, COLORS["danger"]),
            ("累计重连次数:", self.total_var, COLORS["text"]),
        ]
        for i, (label, var, color) in enumerate(left_items):
            Label(status_frame, text=label, font=("Microsoft YaHei", 10),
                  bg=COLORS["card"], fg=COLORS["text_secondary"]).grid(row=i, column=0, sticky=W, padx=(10, 0), pady=3)
            Label(status_frame, textvariable=var, font=("Microsoft YaHei", 10, "bold"),
                  bg=COLORS["card"], fg=color).grid(row=i, column=1, sticky=W, padx=(5, 15), pady=3)

        # 右列（网关后紧跟延迟，用橙色高亮）
        right_items = [
            ("信号强度:", self.signal_var, COLORS["primary"]),
            ("信道:", self.channel_var, COLORS["text"]),
            ("传输速率:", self.tx_rate_var, COLORS["success"]),
            ("IPv4 地址:", self.ipv4_var, COLORS["info"]),
            ("网关 / 延迟:", self.gateway_var, COLORS["text_secondary"]),
        ]
        for i, (label, var, color) in enumerate(right_items):
            Label(status_frame, text=label, font=("Microsoft YaHei", 10),
                  bg=COLORS["card"], fg=COLORS["text_secondary"]).grid(row=i, column=2, sticky=W, padx=(20, 0), pady=3)
            Label(status_frame, textvariable=var, font=("Microsoft YaHei", 10, "bold"),
                  bg=COLORS["card"], fg=color).grid(row=i, column=3, sticky=W, padx=(5, 10), pady=3)

        status_frame.grid_columnconfigure(1, weight=1)
        status_frame.grid_columnconfigure(3, weight=1)

        # ── 设置面板 ──
        settings_frame = Frame(main_frame, bg=COLORS["card"], relief=SUNKEN, bd=1)
        settings_frame.pack(fill=X, pady=(0, 10))

        Label(settings_frame, text="设置", font=("Microsoft YaHei", 11, "bold"),
              bg=COLORS["card"], fg=COLORS["text"]).grid(row=0, column=0, columnspan=4, sticky=W, padx=10, pady=(8, 4))

        # 目标 SSID
        Label(settings_frame, text="目标 SSID:", bg=COLORS["card"], font=("Microsoft YaHei", 10)).grid(
            row=1, column=0, sticky=W, padx=10, pady=4)
        self.ssid_var = StringVar(value=self.config.get("target_ssid", ""))
        self.ssid_entry = Entry(settings_frame, textvariable=self.ssid_var, width=22,
                                font=("Microsoft YaHei", 10))
        self.ssid_entry.grid(row=1, column=1, sticky=W, padx=5, pady=4)
        Label(settings_frame, text="（留空=自动检测）", bg=COLORS["card"], font=("Microsoft YaHei", 9),
              fg=COLORS["text_secondary"]).grid(row=1, column=2, sticky=W, padx=5, pady=4)

        # 检测间隔
        Label(settings_frame, text="检测间隔(秒):", bg=COLORS["card"], font=("Microsoft YaHei", 10)).grid(
            row=2, column=0, sticky=W, padx=10, pady=4)
        self.interval_var = IntVar(value=self.config.get("check_interval", 5))
        Entry(settings_frame, textvariable=self.interval_var, width=10,
              font=("Microsoft YaHei", 10)).grid(row=2, column=1, sticky=W, padx=5, pady=4)

        # 最大重试
        Label(settings_frame, text="最大重试次数:", bg=COLORS["card"], font=("Microsoft YaHei", 10)).grid(
            row=3, column=0, sticky=W, padx=10, pady=4)
        self.max_retry_var = IntVar(value=self.config.get("max_retry", 10))
        Entry(settings_frame, textvariable=self.max_retry_var, width=10,
              font=("Microsoft YaHei", 10)).grid(row=3, column=1, sticky=W, padx=5, pady=4)

        # 重连间隔
        Label(settings_frame, text="重连间隔(秒):", bg=COLORS["card"], font=("Microsoft YaHei", 10)).grid(
            row=4, column=0, sticky=W, padx=10, pady=4)
        self.reconnect_delay_var = IntVar(value=self.config.get("reconnect_delay", 3))
        Entry(settings_frame, textvariable=self.reconnect_delay_var, width=10,
              font=("Microsoft YaHei", 10)).grid(row=4, column=1, sticky=W, padx=5, pady=4)

        # 自动启动
        self.auto_start_var = IntVar(value=1 if self.config.get("auto_start") else 0)
        Checkbutton(settings_frame, text="启动时自动开始监控", variable=self.auto_start_var,
                    bg=COLORS["card"], font=("Microsoft YaHei", 10)).grid(
            row=5, column=0, columnspan=2, sticky=W, padx=10, pady=(0, 4))

        # 禁用 USB 节能
        self.usb_suspend_var = IntVar(value=1 if self.config.get("disable_usb_suspend", True) else 0)
        Checkbutton(settings_frame, text="禁用 USB 节能（推荐，减少断连）", variable=self.usb_suspend_var,
                    bg=COLORS["card"], font=("Microsoft YaHei", 10),
                    fg=COLORS["success"]).grid(
            row=6, column=0, columnspan=2, sticky=W, padx=10, pady=(0, 4))

        # 网卡重启阈值
        Label(settings_frame, text="失败N次后重启网卡:", bg=COLORS["card"], font=("Microsoft YaHei", 10)).grid(
            row=7, column=0, sticky=W, padx=10, pady=4)
        self.restart_after_var = IntVar(value=self.config.get("restart_adapter_after", 3))
        Entry(settings_frame, textvariable=self.restart_after_var, width=10,
              font=("Microsoft YaHei", 10)).grid(row=7, column=1, sticky=W, padx=5, pady=4)

        # 驱动程序路径
        Label(settings_frame, text="驱动安装程序:", bg=COLORS["card"], font=("Microsoft YaHei", 10)).grid(
            row=8, column=0, sticky=W, padx=10, pady=4)
        self.driver_exe_var = StringVar(value=self.config.get("driver_exe_path", ""))
        Entry(settings_frame, textvariable=self.driver_exe_var, width=30,
              font=("Microsoft YaHei", 9)).grid(row=8, column=1, columnspan=3, sticky=W, padx=5, pady=4)

        # 驱动静默响应文件
        Label(settings_frame, text="静默响应文件(.iss):", bg=COLORS["card"], font=("Microsoft YaHei", 10)).grid(
            row=9, column=0, sticky=W, padx=10, pady=(4, 8))
        self.driver_iss_var = StringVar(value=self.config.get("driver_iss_path", ""))
        Entry(settings_frame, textvariable=self.driver_iss_var, width=30,
              font=("Microsoft YaHei", 9)).grid(row=9, column=1, columnspan=3, sticky=W, padx=5, pady=(4, 8))

        # ── 按钮栏 ──
        btn_frame = Frame(main_frame, bg=COLORS["bg"])
        btn_frame.pack(fill=X, pady=(0, 8))

        self.start_btn = Button(btn_frame, text="▶  开始监控", command=self.start_monitor,
                                bg=COLORS["primary"], fg="white", font=("Microsoft YaHei", 10, "bold"),
                                relief="flat", padx=16, pady=5, cursor="hand2")
        self.start_btn.pack(side=LEFT, padx=4)

        self.pause_btn = Button(btn_frame, text="⏸  暂停", command=self.pause_monitor,
                                bg=COLORS["warning"], fg="white", font=("Microsoft YaHei", 10, "bold"),
                                relief="flat", padx=16, pady=5, cursor="hand2", state=DISABLED)
        self.pause_btn.pack(side=LEFT, padx=4)

        self.stop_btn = Button(btn_frame, text="■  停止", command=self.stop_monitor,
                               bg=COLORS["danger"], fg="white", font=("Microsoft YaHei", 10, "bold"),
                               relief="flat", padx=16, pady=5, cursor="hand2", state=DISABLED)
        self.stop_btn.pack(side=LEFT, padx=4)

        self.log_clear_btn = Button(btn_frame, text="清空日志", command=self.clear_log,
                                    bg=COLORS["text_secondary"], fg="white", font=("Microsoft YaHei", 10),
                                    relief="flat", padx=12, pady=5, cursor="hand2")
        self.log_clear_btn.pack(side=RIGHT, padx=4)

        self.diagnose_btn = Button(btn_frame, text="🔍 状态诊断", command=self.diagnose,
                                   bg=COLORS["cta"], fg="white", font=("Microsoft YaHei", 10),
                                   relief="flat", padx=12, pady=5, cursor="hand2")
        self.diagnose_btn.pack(side=RIGHT, padx=4)

        self.save_btn = Button(btn_frame, text="💾 保存设置", command=self.save_settings,
                               bg=COLORS["primary"], fg="white", font=("Microsoft YaHei", 10),
                               relief="flat", padx=12, pady=5, cursor="hand2")
        self.save_btn.pack(side=RIGHT, padx=4)

        # ── 日志区域 ──
        log_frame = Frame(main_frame, bg=COLORS["bg"])
        log_frame.pack(fill=BOTH, expand=True)

        Label(log_frame, text="运行日志", font=("Microsoft YaHei", 10, "bold"),
              bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor=W)

        text_frame = Frame(log_frame, bg="#1E293B")
        text_frame.pack(fill=BOTH, expand=True)

        self.log_text = Text(
            text_frame, bg="#1E293B", fg="#E2E8F0", insertbackground="white",
            font=("Consolas", 9), wrap=WORD, relief="flat", padx=8, pady=6,
            state=DISABLED
        )
        scrollbar = Scrollbar(text_frame, orient=VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.log_text.pack(fill=BOTH, expand=True)

        # 日志颜色标签
        self.log_text.tag_config("INFO", foreground="#E2E8F0")
        self.log_text.tag_config("SUCCESS", foreground=COLORS["success"])
        self.log_text.tag_config("WARN", foreground=COLORS["warning"])
        self.log_text.tag_config("ERROR", foreground=COLORS["danger"])
        self.log_text.tag_config("CRITICAL", foreground=COLORS["cta"], font=("Consolas", 9, "bold"))

        # ─── 底部状态栏 ───
        self.bottom_label = Label(self.root, text="就绪  | 适用于 Windows 10 Pro",
                                  bg=COLORS["card"], fg=COLORS["text_secondary"], font=("Microsoft YaHei", 8),
                                  anchor=W, padx=8)
        self.bottom_label.pack(side=BOTTOM, fill=X)

    # ── 日志写入 ──
    def _write_log(self, msg, level="INFO"):
        self.log_text.configure(state=NORMAL)
        self.log_text.insert(END, msg + "\n", level)
        self.log_text.see(END)
        self.log_text.configure(state=DISABLED)

    def _poll_log(self):
        """定时从队列读取日志，并直接从监控线程读取状态"""
        try:
            while True:
                item = self.log_queue.get_nowait()
                if isinstance(item, tuple) and len(item) == 2:
                    msg_type, payload = item
                    if msg_type == "LOG":
                        for lvl in ["CRITICAL", "ERROR", "WARN", "SUCCESS", "INFO"]:
                            if f"[{lvl}]" in payload:
                                self._write_log(payload, lvl)
                                break
                        else:
                            self._write_log(payload, "INFO")
                else:
                    self._write_log(item, "INFO")
        except queue.Empty:
            pass

        # 直接从监控线程读取状态（无 subprocess 调用，零开销）
        if self.monitor and self.monitor.is_alive():
            self.status_var.set(self.monitor.status)
            self.retry_var.set(str(self.monitor.retry_count))
            self.total_var.set(str(self.monitor.total_reconnects))
            if self.monitor.is_connected:
                self.wifi_var.set(self.monitor.current_ssid)
                self.signal_var.set(self.monitor.signal or "--")
                self.channel_var.set(self.monitor.channel or "--")
                tx = self.monitor.tx_rate or ""
                if tx and "Mbps" not in tx.upper() and "MBPS" not in tx:
                    tx += " Mbps"
                self.tx_rate_var.set(tx if tx else "--")
                self.ipv4_var.set(self.monitor.ipv4 or "--")
                gw = self.monitor.gateway or "--"
                ping = self.monitor.ping_ms or "--"
                self.gateway_var.set(f"{gw}  |  {ping}")
            else:
                self.wifi_var.set("未连接")
                self.signal_var.set("--")
                self.channel_var.set("--")
                self.tx_rate_var.set("--")
                self.ipv4_var.set("--")
                self.gateway_var.set(self.monitor.ping_ms or "--")
        elif self.monitor and not self.monitor.is_alive():
            self.status_var.set(self.monitor.status)
            if "超限" in self.monitor.status and not self._stopped_handled:
                self._stopped_handled = True
                self._on_monitor_stopped()

        self.root.after(500, self._poll_log)

    # ── 控制方法 ──
    def start_monitor(self):
        if self.monitor and self.monitor.is_alive():
            messagebox.showinfo("提示", "监控已在运行中")
            return

        self._stopped_handled = False   # 重置标志

        # 检查 Wi-Fi 接口
        info = get_current_wifi_info()
        if info is None:
            messagebox.showwarning("警告", "无法检测到 Wi-Fi 接口，请确认：\n"
                                   "1. 无线网卡已启用\n"
                                   "2. 已安装无线网卡驱动\n\n"
                                   "程序将继续运行，但可能无法正常工作。")

        self.config["max_retry"] = self.max_retry_var.get()
        self.config["check_interval"] = self.interval_var.get()
        self.config["reconnect_delay"] = self.reconnect_delay_var.get()
        self.config["target_ssid"] = self.ssid_var.get().strip()

        self.monitor = MonitorThread(self.config, self.log_queue)
        self.monitor.start()

        # 更新按钮状态
        self.start_btn.configure(state=DISABLED)
        self.pause_btn.configure(state=NORMAL, text="⏸  暂停")
        self.stop_btn.configure(state=NORMAL)
        self.ssid_entry.configure(state="readonly")

        self._write_log("=" * 50, "INFO")
        self._write_log("监控已启动", "SUCCESS")
        self._write_log("=" * 50, "INFO")

        self.bottom_label.configure(text="监控运行中...")

    def pause_monitor(self):
        if not self.monitor or not self.monitor.is_alive():
            return
        if self.monitor._paused:
            self.monitor.resume()
            self.pause_btn.configure(text="⏸  暂停")
            self._write_log("监控已恢复", "SUCCESS")
            self.bottom_label.configure(text="监控运行中...")
        else:
            self.monitor.pause()
            self.pause_btn.configure(text="▶  继续")
            self._write_log("监控已暂停", "WARN")
            self.bottom_label.configure(text="监控已暂停")

    def stop_monitor(self):
        if not self.monitor or not self.monitor.is_alive():
            return
        self.monitor.stop()
        self._stopped_handled = True
        self._on_monitor_stopped()
        self._write_log("用户手动停止监控", "WARN")

    def _on_monitor_stopped(self):
        self.start_btn.configure(state=NORMAL)
        self.pause_btn.configure(state=DISABLED, text="⏸  暂停")
        self.stop_btn.configure(state=DISABLED)
        self.ssid_entry.configure(state=NORMAL)
        self.bottom_label.configure(text="监控已停止")

    def clear_log(self):
        self.log_text.configure(state=NORMAL)
        self.log_text.delete("1.0", END)
        self.log_text.configure(state=DISABLED)

    def show_changelog(self):
        """显示更新日志弹窗"""
        win = Toplevel(self.root)
        win.title(f"更新日志 - {APP_VERSION}")
        win.geometry("600x520")
        win.transient(self.root)
        win.grab_set()

        # 标题
        Label(
            win, text=f"Wi-Fi 自动重连管理工具  {APP_VERSION}",
            font=("Microsoft YaHei", 14, "bold"), bg="#1E40AF", fg="white",
            pady=10
        ).pack(fill=X)

        # 日志内容
        text_frame = Frame(win, bg="#1E293B")
        text_frame.pack(fill=BOTH, expand=True, padx=2, pady=2)

        log_text = Text(
            text_frame, bg="#1E293B", fg="#E2E8F0", insertbackground="white",
            font=("Consolas", 10), wrap=WORD, relief="flat", padx=12, pady=10
        )
        scrollbar = Scrollbar(text_frame, orient=VERTICAL, command=log_text.yview)
        log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=RIGHT, fill=Y)
        log_text.pack(fill=BOTH, expand=True)

        # 颜色标签
        log_text.tag_config("version", foreground="#F97316", font=("Consolas", 11, "bold"))
        log_text.tag_config("date", foreground="#64748B", font=("Consolas", 9))
        log_text.tag_config("item", foreground="#E2E8F0")
        log_text.tag_config("separator", foreground="#334155")

        for ver, date, items in CHANGELOG:
            log_text.insert(END, f"  {ver}", "version")
            log_text.insert(END, f"    ({date})\n", "date")
            for item in items:
                log_text.insert(END, f"    • {item}\n", "item")
            log_text.insert(END, f"\n{'─' * 56}\n\n", "separator")

        log_text.configure(state=DISABLED)

        # 关闭按钮
        Button(
            win, text="关闭", command=win.destroy,
            bg="#2563EB", fg="white", font=("Microsoft YaHei", 10, "bold"),
            relief="flat", padx=24, pady=5, cursor="hand2"
        ).pack(pady=10)

    def diagnose(self):
        """显示 Wi-Fi 诊断信息"""
        service = check_wlan_service()

        # 测试 PowerShell 方法
        ps_info = _get_wifi_info_from_powershell()
        # 同时直接执行一次获取 stderr
        ps_test_out, ps_test_err, ps_test_code = run_cmd(
            ["powershell", "-NoProfile", "-Command",
             "$p = Get-NetConnectionProfile | Where-Object { $_.InterfaceAlias -match 'wlan|wi-fi|无线' } | Select-Object -First 1; if ($p) { 'SSID:' + $p.Name + '|State:connected' } else { 'State:disconnected' }"],
            timeout=10
        )

        # 测试 netsh 方法
        all_paths = _find_all_netsh()
        netsh_results = []
        for p in all_paths:
            out, err, code = run_cmd([p, "wlan", "show", "interfaces"])
            netsh_results.append((p, out, err, code, len(out)))

        # 最终获取结果
        info = get_current_wifi_info()
        connected, ssid = is_wifi_connected()

        diag = "======== Wi-Fi 诊断报告 ========\n\n"
        diag += f"Python: {sys.version.split()[0]} ({sys.maxsize.bit_length() + 1}位)\n"
        diag += f"WLAN 服务: {service}\n"
        diag += f"连接状态: {'✓ 已连接' if connected else '✗ 未连接'}\n"

        if info:
            diag += f"\n--- 解析结果 ---\n"
            diag += f"SSID: {info.get('ssid', '无')}\n"
            diag += f"状态: {info.get('state', '无')}\n"
            diag += f"网卡: {info.get('name', '无')}\n"
            diag += f"配置文件: {info.get('profile', '无')}\n"
            diag += f"信号: {info.get('signal', '无')}\n"
            diag += f"信道: {info.get('channel', '无')}\n"
            diag += f"速率: {info.get('tx_rate', '无')}\n"
        else:
            diag += "\n⚠ 无法解析 Wi-Fi 信息\n"

        diag += f"\n--- PowerShell 极简测试 ---\n"
        diag += f"返回码: {ps_test_code}\n"
        diag += f"stdout: {ps_test_out if ps_test_out else '(空)'}\n"
        if ps_test_err:
            diag += f"stderr: {ps_test_err}\n"

        diag += f"\n--- PowerShell 完整方法 ---\n"
        if ps_info:
            diag += "成功，字段如下:\n"
            for k, v in ps_info.items():
                diag += f"  {k} = {v}\n"
        else:
            diag += "失败或返回空\n"

        diag += "\n--- netsh 直接调用 ---\n"
        for p, out, err, code, out_len in netsh_results:
            short = os.path.basename(p) if "\\" in p else p
            status = "✓" if (code == 0 and out) else "✗"
            diag += f"[{short}] code={code} len={out_len} {status}\n"
            if err:
                diag += f"  err: {err[:120]}\n"

        # 最佳 netsh 输出
        best = max(netsh_results, key=lambda r: len(r[1]), default=None)
        if best and best[1]:
            diag += f"\n======== 最佳 netsh 完整输出 ========\n{best[1]}"

        self._show_dialog(diag)

    def _show_dialog(self, text):
        """显示诊断窗口（使用 Toplevel 避免阻塞主线程）"""
        win = Toplevel(self.root)
        win.title("Wi-Fi 状态诊断")
        win.geometry("600x500")
        win.configure(bg="#F8FAFC")
        win.transient(self.root)
        win.grab_set()

        txt = Text(win, bg="#1E293B", fg="#E2E8F0", insertbackground="white",
                   font=("Consolas", 9), wrap=WORD)
        scroll = Scrollbar(win, orient=VERTICAL, command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side=RIGHT, fill=Y)
        txt.pack(fill=BOTH, expand=True, padx=10, pady=10)
        txt.insert(END, text)
        txt.configure(state=DISABLED)

        Button(win, text="关闭", command=win.destroy,
               bg="#2563EB", fg="white", font=("Microsoft YaHei", 10),
               relief="flat", padx=20, pady=5, cursor="hand2").pack(pady=8)

    def _auto_clear_log(self):
        """每隔 30 秒自动清空日志（避免日志堆积）"""
        self.clear_log()
        self.root.after(30000, self._auto_clear_log)

    def save_settings(self):
        self.config["max_retry"] = self.max_retry_var.get()
        self.config["check_interval"] = self.interval_var.get()
        self.config["reconnect_delay"] = self.reconnect_delay_var.get()
        self.config["target_ssid"] = self.ssid_var.get().strip()
        self.config["auto_start"] = bool(self.auto_start_var.get())
        self.config["disable_usb_suspend"] = bool(self.usb_suspend_var.get())
        self.config["restart_adapter_after"] = self.restart_after_var.get()
        self.config["driver_exe_path"] = self.driver_exe_var.get().strip()
        self.config["driver_iss_path"] = self.driver_iss_var.get().strip()
        save_config(self.config)
        messagebox.showinfo("保存成功", "设置已保存到配置文件")

        if self.monitor and self.monitor.is_alive():
            self.monitor.config = copy.deepcopy(self.config)
            self._write_log("设置已更新（部分设置将在下次检测周期生效）", "INFO")

    def _on_close(self):
        if self.monitor and self.monitor.is_alive():
            resp = messagebox.askyesno("确认退出", "监控正在运行中，确定要退出吗？")
            if not resp:
                return
            self.monitor.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ───────────────────── 入口 ─────────────────────
if __name__ == "__main__":
    # 确保在 Windows 上运行
    if os.name != "nt":
        print("⚠ 此工具仅适用于 Windows 10/11 系统")
        print("当前系统非 Windows，程序将以演示模式运行（GUI 可显示，但 Wi-Fi 功能不可用）")

    try:
        app = WiFiMonitorApp()
        app.run()
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        print("=" * 50)
        print("程序启动失败！错误信息：")
        print("=" * 50)
        print(err_msg)
        print("=" * 50)
        # 尝试用 tkinter 弹窗显示错误
        try:
            from tkinter import messagebox
            root = Tk()
            root.withdraw()
            messagebox.showerror("启动错误", f"程序启动失败：\n\n{err_msg}\n\n请截图发给开发者。")
        except Exception:
            pass
        input("按回车键退出...")